#!/usr/bin/env python3
"""Fetch a bounded batch of questionnaires that are not collected yet.

    python3 scripts/backfill.py --limit 40 --per-year 8 --years 2018 2020 2022 2023 2024   # a small pilot
    python3 scripts/backfill.py --limit 2500                                               # one day's batch
    python3 scripts/backfill.py --dry-run                                                  # show what it would do

Picks ids from data/id_inventory.parquet (announcements first seen in config.MIN_YEAR, 2025, or later,
unless --years says otherwise), newest first, skips any id the state file already
settled and any id listed in --have (a file with one "portal,id" per line, or a folder of
usastaffing_<id>.txt / monster_<id>.txt files). Stops at once on any refusal (exit code 3).
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from usajq import config  # noqa: E402
from usajq import fetch  # noqa: E402


def have_ids(path):
    out = set()
    if not path:
        return out
    p = Path(path)
    if p.is_dir():
        for f in p.iterdir():
            if f.suffix == ".txt" and "_" in f.stem:
                portal, qid = f.stem.split("_", 1)
                out.add((portal, qid))
    elif p.exists():
        for line in p.read_text().splitlines():
            if "," in line:
                a, b = line.strip().split(",", 1)
                out.add((a, b))
    return out


def pick(args, state):
    con = duckdb.connect()
    inv = con.execute(
        f"select questionnaire_id, portal, url, first_seen_month from '{config.DATA_DIR}/id_inventory.parquet' "
        "where questionnaire_id is not null and questionnaire_id <> ''"
    ).fetchdf()
    have = have_ids(args.have)
    rows = []
    for r in inv.itertuples():
        if (r.portal, r.questionnaire_id) in have or state.done(r.portal, r.questionnaire_id):
            continue
        if args.portal != "all" and r.portal != args.portal:
            continue
        year = r.first_seen_month[:4]
        if args.years:
            if year not in args.years:
                continue
        elif int(year) < config.MIN_YEAR:
            continue
        rows.append((year, r.first_seen_month, r.portal, r.questionnaire_id, r.url))
    # newest first, then spread by year when asked
    rows.sort(key=lambda x: (x[1], x[3]), reverse=True)
    if args.per_year:
        # an evenly spaced sample from each year and portal, so a small run covers the whole year
        groups = {}
        for row in rows:
            groups.setdefault((row[0], row[2]), []).append(row)
        out = []
        for g in groups.values():
            n = min(args.per_year, len(g))
            step = len(g) / n
            out.extend(g[int(i * step)] for i in range(n))
        out.sort(key=lambda x: (x[1], x[3]), reverse=True)
        rows = out
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=config.MAX_REQUESTS_PER_DAY)
    ap.add_argument("--portal", default="usastaffing", choices=["usastaffing", "monster", "all"])
    ap.add_argument("--years", nargs="*")
    ap.add_argument("--per-year", type=int)
    ap.add_argument("--have", help="file or folder of ids already collected")
    ap.add_argument("--raw-dir", default=str(config.BUILD_DIR / "raw"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    state = fetch.State()
    budget = fetch.todays_budget(state, args.limit)
    rows = pick(args, state)[:budget]
    print(f"budget today: {budget}; selected: {len(rows)}")
    by = {}
    for y, _, portal, _, _ in rows:
        by[(y, portal)] = by.get((y, portal), 0) + 1
    print(json.dumps({f"{k[0]}:{k[1]}": v for k, v in sorted(by.items())}))
    if args.dry_run or not rows:
        return 0
    raw = Path(args.raw_dir)
    usa = [(qid, fetch.usastaffing_url(qid)) for _, _, portal, qid, _ in rows if portal == "usastaffing"]
    mon = [(qid, url) for _, _, portal, qid, url in rows if portal == "monster"]
    counts = {}
    try:
        if usa:
            counts["usastaffing"] = asyncio.run(fetch.fetch_usastaffing(usa, raw, state))
        if mon:
            counts["monster"] = fetch.fetch_monster(mon, raw, state)
    except fetch.Blocked as e:
        print("STOPPED:", e)
        print(json.dumps(counts))
        return fetch.EXIT_BLOCKED
    except fetch.NoContent as e:
        print("STOPPED:", e, "(see the snippet field in the state file; try UQ_HEADED=1)")
        return fetch.EXIT_NO_CONTENT
    print(json.dumps(counts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
