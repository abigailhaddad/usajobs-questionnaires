#!/usr/bin/env python3
"""Publish a built release or batch to Hugging Face in ONE commit.

    python3 scripts/publish_to_hf.py                          # dry run: checks everything, writes nothing
    python3 scripts/publish_to_hf.py --tag 2025-release --upload
    python3 scripts/publish_to_hf.py --release build/batch --tag batch-2026-11-07 --upload --no-card

Each table is stored as data/<table>/part-<tag>.parquet, so a batch adds files and never
rewrites old ones. The dry run reads the remote only to look for ids that are already published.
"""
import argparse
import os
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from usajq import config  # noqa: E402

TABLES = ("questionnaires", "questions", "sections")
GOOD_STATUS = {"ok", "ok_missing_header", "no_questions", "html_shell", "login_page", "not_a_questionnaire", "monster_not_parsed"}


def check_release(rel: Path):
    """Return (problems, facts). Pure local checks."""
    problems, facts = [], {}
    for t in TABLES:
        if not (rel / f"{t}.parquet").exists():
            problems.append(f"missing {rel / (t + '.parquet')}")
    if problems:
        return problems, facts
    c = duckdb.connect()
    p = lambda t: f"'{rel / (t + '.parquet')}'"
    n_q, = c.execute(f"select count(*) from {p('questionnaires')}").fetchone()
    n_dist, = c.execute(f"select count(distinct portal || ':' || questionnaire_id) from {p('questionnaires')}").fetchone()
    n_k, n_kd = c.execute(f"select count(*), count(distinct question_id) from {p('questions')}").fetchone()
    n_sum, = c.execute(f"select coalesce(sum(n_questions),0) from {p('questionnaires')}").fetchone()
    nulls, = c.execute(f"select count(*) from {p('questionnaires')} where questionnaire_id is null or questionnaire_id = ''").fetchone()
    orphans, = c.execute(
        f"select count(*) from {p('questions')} k left join {p('questionnaires')} q "
        "on k.questionnaire_id = q.questionnaire_id and k.portal = q.portal where q.questionnaire_id is null").fetchone()
    statuses = {r[0] for r in c.execute(f"select distinct parse_status from {p('questionnaires')}").fetchall()}
    leaked, = c.execute(
        f"select count(*) from {p('questionnaires')} where parse_status in ('html_shell','login_page') and raw_text is not null").fetchone()
    facts.update(questionnaires=n_q, distinct=n_dist, questions=n_k, sections=c.execute(f"select count(*) from {p('sections')}").fetchone()[0])
    if n_q == 0:
        problems.append("no questionnaires")
    if n_q != n_dist:
        problems.append(f"questionnaire ids repeat ({n_q} rows, {n_dist} distinct)")
    if n_k != n_kd:
        problems.append(f"question ids repeat ({n_k} rows, {n_kd} distinct)")
    if n_k != n_sum:
        problems.append(f"questions ({n_k}) differ from the sum of n_questions ({n_sum})")
    if nulls:
        problems.append(f"{nulls} questionnaires without an id")
    if orphans:
        problems.append(f"{orphans} questions whose questionnaire is not in the table")
    if statuses - GOOD_STATUS:
        problems.append(f"unknown parse_status values: {sorted(statuses - GOOD_STATUS)}")
    if leaked:
        problems.append(f"{leaked} html_shell/login pages kept their raw text")
    return problems, facts


def remote_overlap(rel: Path):
    """Ids in this release that are already published. Empty if the dataset does not exist yet."""
    from huggingface_hub import HfApi
    from huggingface_hub.utils import RepositoryNotFoundError

    api = HfApi()
    try:
        files = [f for f in api.list_repo_files(config.HF_DATASET, repo_type="dataset") if f.startswith("data/questionnaires/")]
    except RepositoryNotFoundError:
        return None, 0
    if not files:
        return [], 0
    c = duckdb.connect()
    c.execute("install httpfs; load httpfs")
    urls = ", ".join(f"'hf://datasets/{config.HF_DATASET}/{f}'" for f in files)
    n, = c.execute(
        f"select count(*) from (select portal, questionnaire_id from '{rel / 'questionnaires.parquet'}') a "
        f"join (select portal, questionnaire_id from read_parquet([{urls}])) b using (portal, questionnaire_id)").fetchone()
    return files, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", default=str(config.BUILD_DIR / "release"))
    ap.add_argument("--tag", default="2025-release")
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--no-card", action="store_true", help="do not send README.md (batches after the first)")
    ap.add_argument("--allow-overlap", action="store_true")
    args = ap.parse_args()
    rel = Path(args.release)
    problems, facts = check_release(rel)
    print("local checks:", facts)
    if problems:
        print("PROBLEMS:")
        for x in problems:
            print("  -", x)
        return 1
    print("local checks passed")
    files, overlap = remote_overlap(rel)
    if files is None:
        print(f"remote: {config.HF_DATASET} does not exist yet; --upload would create it as a public dataset")
    else:
        print(f"remote: {config.HF_DATASET} has {len(files)} questionnaire file(s); {overlap} id(s) here are already published")
        if overlap and not args.allow_overlap:
            print("refusing: overlapping ids (use --allow-overlap to publish anyway)")
            return 1
    ops_plan = {f"data/{t}/part-{args.tag}.parquet": rel / f"{t}.parquet" for t in TABLES}
    if not args.no_card and (rel / "README.md").exists():
        ops_plan["README.md"] = rel / "README.md"
    for dest, src in ops_plan.items():
        print(f"  {dest}  <-  {src}  ({src.stat().st_size/1e6:.1f} MB)")
    if not args.upload:
        print("dry run: nothing uploaded (add --upload to commit)")
        return 0
    from huggingface_hub import CommitOperationAdd, HfApi

    api = HfApi(token=os.environ.get("HF_TOKEN"))
    api.create_repo(config.HF_DATASET, repo_type="dataset", exist_ok=True)
    api.create_commit(
        repo_id=config.HF_DATASET, repo_type="dataset",
        operations=[CommitOperationAdd(path_in_repo=d, path_or_fileobj=str(s)) for d, s in ops_plan.items()],
        commit_message=f"Add {args.tag}: {facts['questionnaires']:,} questionnaires, {facts['questions']:,} questions",
    )
    print("committed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
