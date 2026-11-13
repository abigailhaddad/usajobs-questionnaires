#!/usr/bin/env python3
"""Write one small copy of the questionnaires table for the dataset explorer.

    python3 scripts/build_explorer_file.py              # build and check; writes build/explorer/questionnaires.parquet
    python3 scripts/build_explorer_file.py --upload     # also replace explorer/questionnaires.parquet on Hugging Face

The published table is a folder of part files, one per batch, so it grows by a file a day. The explorer
reads every part with range requests, one after another, and each new file makes it slower. This copy is
every published row with every column except raw_text (about 90% of the bytes, and the explorer never
shows it), in a single file with a single row group. It is rebuilt from the published parts after each
batch, so it never holds anything the parts don't. The parts under data/ stay the record; this file sits
outside data/ so the dataset viewer and `load_dataset` don't see it.
"""
import argparse
import os
import sys
import time
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from usajq import config  # noqa: E402

DEST = "explorer/questionnaires.parquet"
DROP = "raw_text"


def build(sources, out: Path):
    """Write the copy from `sources` (paths or URLs of the part files). Return (problems, facts)."""
    c = duckdb.connect()
    c.execute("install httpfs; load httpfs")
    src = "read_parquet([" + ", ".join(f"'{s}'" for s in sources) + "], union_by_name=true)"
    cols = [r[0] for r in c.execute(f"describe select * from {src}").fetchall()]
    keep = [x for x in cols if x != DROP]
    out.parent.mkdir(parents=True, exist_ok=True)
    c.execute(f"create table parts as select * from {src}")
    c.execute(
        "copy (select " + ", ".join(f'"{x}"' for x in keep) + " from parts order by portal, questionnaire_id) "
        f"to '{out}' (format parquet, compression zstd, row_group_size 10000000)"
    )
    # Check the written file against the parts, not against the query that wrote it.
    n_parts, = c.execute("select count(*) from parts").fetchone()
    n_out, n_dist = c.execute(f"select count(*), count(distinct portal || ':' || questionnaire_id) from '{out}'").fetchone()
    out_cols = [r[0] for r in c.execute(f"describe select * from '{out}'").fetchall()]
    missing, = c.execute(
        f"select count(*) from (select portal, questionnaire_id from parts except select portal, questionnaire_id from '{out}')"
    ).fetchone()
    # Every kept value, not just the keys: rows in the parts with no identical row in the copy.
    keep_sql = ", ".join(f'"{x}"' for x in keep)
    changed, = c.execute(f"select count(*) from (select {keep_sql} from parts except all select {keep_sql} from '{out}')").fetchone()
    row_groups, = c.execute(f"select count(distinct row_group_id) from parquet_metadata('{out}')").fetchone()
    facts = dict(parts=len(sources), rows_in_parts=n_parts, rows=n_out, columns=len(out_cols), row_groups=row_groups,
                 mb=round(out.stat().st_size / 1e6, 2))
    problems = []
    if n_out != n_parts:
        problems.append(f"{n_out} rows written, {n_parts} in the parts")
    if n_dist != n_out:
        problems.append(f"questionnaire ids repeat ({n_out} rows, {n_dist} distinct)")
    if out_cols != keep:
        problems.append(f"columns differ from the parts: {out_cols} vs {keep}")
    if missing:
        problems.append(f"{missing} questionnaires in the parts are not in the copy")
    if changed:
        problems.append(f"{changed} rows in the parts have no identical row in the copy")
    if row_groups != 1:
        problems.append(f"{row_groups} row groups, expected 1")
    return problems, facts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(config.BUILD_DIR / "explorer" / "questionnaires.parquet"))
    ap.add_argument("--upload", action="store_true")
    args = ap.parse_args()
    from huggingface_hub import CommitOperationAdd, HfApi

    api = HfApi(token=os.environ.get("HF_TOKEN"))
    files = sorted(f for f in api.list_repo_files(config.HF_DATASET, repo_type="dataset")
                   if f.startswith("data/questionnaires/") and f.endswith(".parquet"))
    if not files:
        print("no published questionnaire files")
        return 1
    out = Path(args.out)
    problems, facts = build([f"hf://datasets/{config.HF_DATASET}/{f}" for f in files], out)
    print("explorer copy:", facts)
    if problems:
        print("PROBLEMS:")
        for x in problems:
            print("  -", x)
        return 1
    if not args.upload:
        print(f"dry run: wrote {out}; nothing uploaded (add --upload)")
        return 0
    commit_with_retry(
        api,
        lambda: [CommitOperationAdd(path_in_repo=DEST, path_or_fileobj=str(out))],
        f"Explorer copy of questionnaires: {facts['rows']:,} rows from {facts['parts']} part files",
    )
    print(f"committed {DEST}")
    return 0


# On 2026-11-12 the Hub rejected this commit with "an LFS pointer pointed to a file that does not exist",
# about 0.2 seconds after hf_xet reported the upload finished (run 43246945240). The same code path had
# committed the day's batch seconds earlier. A rejected commit writes nothing, and this file is a whole-file
# replacement rebuilt from the parts, so trying again (with fresh operations, so the file is uploaded again)
# is safe. Any other error, or the same error after the last try, still fails the run.
RETRY_WAITS = (10, 30, 90)


def commit_with_retry(api, make_operations, message, waits=RETRY_WAITS, sleep=time.sleep):
    from huggingface_hub.errors import BadRequestError

    for i in range(len(waits) + 1):
        try:
            return api.create_commit(repo_id=config.HF_DATASET, repo_type="dataset",
                                     operations=make_operations(), commit_message=message)
        except BadRequestError as e:
            if "LFS pointer" not in str(e) or i == len(waits):
                raise
            print(f"commit rejected ({e.__class__.__name__}: LFS pointer to a missing file); "
                  f"trying again in {waits[i]}s ({i + 1} of {len(waits)})", flush=True)
            sleep(waits[i])


if __name__ == "__main__":
    sys.exit(main())
