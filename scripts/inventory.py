#!/usr/bin/env python3
"""Count and list every questionnaire link in the announcement dataset, read over HTTPS.

Reads only the columns it needs, one monthly file at a time, and writes small per-month
Parquet parts to build/inventory_parts/. Nothing big is downloaded to disk.

    python3 scripts/inventory.py            # all months, resumable
    python3 scripts/inventory.py --combine  # combine the parts into data/id_inventory.parquet
"""
import argparse
import sys
import time
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from usajq import config  # noqa: E402

PARTS = config.BUILD_DIR / "inventory_parts"
USA_RE = r"https?://[^\s\x22\x27<>)]*ViewQuestionnaire/[0-9]+"
MON_RE = r"https?://jobs\.monstergovt\.com/[^\s\x22\x27<>)]+"


def month_files():
    from huggingface_hub import HfApi

    names = [s for s in HfApi().list_repo_files(config.ANNOUNCEMENTS_DATASET, repo_type="dataset")
             if s.startswith("data/") and s.endswith(".parquet")]
    return sorted(names)


def one_month(con, name):
    out = PARTS / (Path(name).stem + ".parquet")
    if out.exists():
        return "skip"
    src = f"hf://datasets/{config.ANNOUNCEMENTS_DATASET}/{name}"
    sql = f"""
    copy (
      with a as (
        select usajobsControlNumber as control_number, announcementNumber as announcement_number,
               hiringAgencyName as agency, positionOpenDate as open_date, vendor,
               occupationalSeries as series, text
        from read_parquet('{src}')
      ),
      links as (
        select control_number, announcement_number, agency, open_date, vendor, series,
               'usastaffing' as portal, unnest(regexp_extract_all(text, '{USA_RE}')) as url from a
        union all
        select control_number, announcement_number, agency, open_date, vendor, series,
               'monster' as portal, unnest(regexp_extract_all(text, '{MON_RE}')) as url from a
      )
      select '{Path(name).stem}' as source_month, * from links
    ) to '{out}' (format parquet, compression zstd)
    """
    con.execute(sql)
    tot = con.execute(
        f"select count(*), count(*) filter (where regexp_matches(text, 'ViewQuestionnaire|monstergovt')) "
        f"from (select text from read_parquet('{src}'))"
    ).fetchone()
    (PARTS / (Path(name).stem + ".counts")).write_text(f"{tot[0]},{tot[1]}\n")
    return "ok"


def combine():
    con = duckdb.connect()
    rows = []
    for f in sorted(PARTS.glob("*.counts")):
        a, b = f.read_text().strip().split(",")
        rows.append((f.stem, int(a), int(b)))
    import pandas as pd

    pd.DataFrame(rows, columns=["source_month", "announcements", "announcements_with_link"]).to_parquet(
        config.DATA_DIR / "announcement_link_rates.parquet", index=False)
    # One row per questionnaire. Compact on purpose (about 7 MB for 2.3 million rows): the USA Staffing url
    # is built from the id, and agency, series and dates come from a join on control_number when needed.
    con.execute(f"""
    copy (
      select portal, questionnaire_id, first_seen_month, n_announcements::smallint as n_announcements,
             control_number, case when portal = 'monster' then url end as url
      from (
        select
          case when portal='usastaffing' then regexp_extract(url, 'ViewQuestionnaire/([0-9]+)', 1)
               else coalesce(nullif(regexp_extract(url, '[?&]jnum=([0-9]+)', 1), ''), nullif(regexp_extract(url, '[?&]J=([0-9]+)', 1), '')) end as questionnaire_id,
          portal,
          min(url) as url,
          min(source_month) as first_seen_month,
          count(distinct control_number) as n_announcements,
          any_value(control_number order by source_month) as control_number
        from read_parquet('{PARTS}/*.parquet')
        group by 1, 2
      )
      where questionnaire_id is not null and questionnaire_id <> ''
      order by portal, first_seen_month, questionnaire_id
    ) to '{config.DATA_DIR}/id_inventory.parquet' (format parquet, compression zstd, compression_level 19)
    """)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--combine", action="store_true")
    ap.add_argument("--only", help="a single month file stem, e.g. 2023_06")
    args = ap.parse_args()
    PARTS.mkdir(parents=True, exist_ok=True)
    config.DATA_DIR.mkdir(exist_ok=True)
    if args.combine:
        combine()
        print("combined")
        return
    con = duckdb.connect()
    con.execute("install httpfs; load httpfs")
    for name in month_files():
        if args.only and Path(name).stem != args.only:
            continue
        for attempt in range(6):
            try:
                t = time.time()
                r = one_month(con, name)
                print(f"{name}: {r} ({time.time()-t:.0f}s)", flush=True)
                break
            except Exception as e:  # network throttling or a transient read error: back off and retry
                wait = 20 * (attempt + 1)
                print(f"{name}: {type(e).__name__}: {str(e)[:100]} (retry in {wait}s)", flush=True)
                time.sleep(wait)
        else:
            print(f"{name}: GAVE UP", flush=True)


if __name__ == "__main__":
    main()
