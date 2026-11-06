"""Health check for a backfill run. Exit non-zero, loudly, when something is wrong.

A job that quietly collects nothing looks green and stays that way for weeks, so this checks
the state file and the batch it just built, and the workflow turns any problem into a red run.
"""
import json
import sys
from pathlib import Path

MIN_OK_SHARE = 0.5      # of the attempts in the recent window, how many must have been ok or not_found
WINDOW = 200            # attempts to look at
MIN_PARSED_SHARE = 0.9  # of the ok pages in a batch, how many must parse into questions


def load_attempts(path):
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def check(attempts, today, batch_status=None, expected_min_attempts=1):
    """Return a list of problems (empty means healthy).

    attempts: records from the state file. today: 'YYYY-MM-DD'. batch_status: parse_status counts
    for the batch just built, e.g. {"ok": 1900, "html_shell": 3}.
    """
    problems = []
    todays = [a for a in attempts if a["ts"].startswith(today)]
    if len(todays) < expected_min_attempts:
        problems.append(f"only {len(todays)} attempts today (expected at least {expected_min_attempts})")
    if any(a["outcome"] == "blocked" for a in todays):
        problems.append("the site refused a request today (outcome blocked); a person must look before the next run")
    recent = attempts[-WINDOW:]
    if len(recent) >= 20:
        good = sum(1 for a in recent if a["outcome"] in ("ok", "not_found"))
        if good / len(recent) < MIN_OK_SHARE:
            problems.append(f"only {good} of the last {len(recent)} attempts returned a questionnaire or a clear not-found")
    if todays and all(a["outcome"] == "error" for a in todays) and len(todays) >= 8:
        problems.append("every attempt today was an error: the fetch method may have stopped working")
    if batch_status:
        ok = batch_status.get("ok", 0) + batch_status.get("ok_missing_header", 0)
        pages = ok + batch_status.get("no_questions", 0) + batch_status.get("not_a_questionnaire", 0)
        if pages >= 20 and ok / pages < MIN_PARSED_SHARE:
            problems.append(f"only {ok} of {pages} pages parsed into questions: the page layout may have changed")
    return problems


def main(argv=None):
    import argparse
    from datetime import datetime, timezone

    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="state/attempts.jsonl")
    ap.add_argument("--batch-stats", help="stats.json written by build_release.py for this batch")
    ap.add_argument("--min-attempts", type=int, default=1)
    args = ap.parse_args(argv)
    batch = None
    if args.batch_stats and Path(args.batch_stats).exists():
        raw = json.loads(Path(args.batch_stats).read_text())
        batch = {k.split(":", 1)[1]: v for k, v in raw.items() if k.startswith("usastaffing:")}
    today = datetime.now(timezone.utc).date().isoformat()
    problems = check(load_attempts(args.state), today, batch, args.min_attempts)
    for p in problems:
        print("[health] PROBLEM:", p)
    if problems:
        return 1
    print("[health] ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
