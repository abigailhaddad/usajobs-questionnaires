#!/usr/bin/env python3
"""Check the parser against the raw files, a second way.

1. Coverage: every non-blank body line in a raw file must come back in some parsed field
   (question text, choices, follow-up text or section intro). Reports files with lines lost.
2. Count: the number of numbered question lines found by a separate regex pass, against the
   parser's question count, per file.
3. Spot check: a seeded random sample of questions plus edge cases, written side by side
   (raw block next to the parsed fields) to evidence/parse_spot_check.csv for reading.

    python3 scripts/verify_parse.py RAW_DIR [--sample 30]
"""
import argparse
import collections
import csv
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from usajq.parse_usastaffing import parse, _footer_start, _header, FIXED_SECTIONS, ASSESSMENT_RE  # noqa: E402


def recovered_lines(r):
    got = set()
    for sec in r["sections"]:
        for l in (sec["intro_text"] or "").split("\n"):
            got.add(l.strip())
    for q in r["questions"]:
        for l in q["question_text"].split("\n"):
            got.add(l.strip())
        for l in (q["trailing_text"] or "").split("\n"):
            got.add(l.strip())
        for o in q["options"]:
            got.add(o["text"].strip())
            got.add((o["letter"] + ". " + o["text"]).strip())
    return got


def body_lines(text):
    lines = text.replace("\r\n", "\n").split("\n")
    _, start = _header(lines)
    end = _footer_start(lines)
    out = []
    for l in lines[start:end]:
        s = l.strip()
        if not s or s == "--Select--":
            continue
        if s.lower() in FIXED_SECTIONS or ASSESSMENT_RE.match(s):
            continue
        out.append(s)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw_dir")
    ap.add_argument("--sample", type=int, default=30)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    d = Path(args.raw_dir)
    files = sorted(p for p in d.iterdir() if p.name.startswith("usastaffing_"))
    status = collections.Counter()
    lost_files, count_mismatch = [], []
    pool = []
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        r = parse(text)
        status[r["parse_status"]] += 1
        if r["parse_status"] not in ("ok", "ok_missing_header"):
            continue
        got = recovered_lines(r)
        missing = []
        for s in body_lines(text):
            if s in got:
                continue
            # a line may be the number-alone marker or a "N." prefixed line
            if re.match(r"^\d+\.$", s):
                continue
            m = re.match(r"^\d+\.\s+(.*)$", s)
            if m and m.group(1).strip() in got:
                continue
            m = re.match(r"^[A-Z]\.\s*(.*)$", s)
            if m and m.group(1).strip() in got:
                continue
            missing.append(s)
        if missing:
            lost_files.append((p.name, len(missing), missing[:2]))
        # Count numbered lines in the body only: the site footer carries a numbered list of its own.
        all_lines = text.replace("\r\n", "\n").split("\n")
        indep = sum(1 for l in all_lines[: _footer_start(all_lines)] if re.match(r"^\d+\.(\s|$)", l.strip()))
        # Numbered lines the parser kept inside text on purpose (a list within a question, a
        # numbered note in a section intro) account for the difference, if the parse is right.
        inner = 0
        for sec in r["sections"]:
            inner += sum(1 for l in (sec["intro_text"] or "").split("\n") if re.match(r"^\d+\.(\s|$)", l))
        for qq in r["questions"]:
            inner += sum(1 for l in qq["question_text"].split("\n")[1:] if re.match(r"^\d+\.(\s|$)", l))
            inner += sum(1 for l in (qq["trailing_text"] or "").split("\n") if re.match(r"^\d+\.(\s|$)", l))
        if indep != len(r["questions"]) + inner:
            count_mismatch.append((p.name, indep, len(r["questions"]), inner))
        for q in r["questions"]:
            pool.append((p.name, q))
    print("files:", len(files), dict(status))
    print("files with body lines not recovered:", len(lost_files))
    for x in lost_files[:6]:
        print("  ", x)
    print("files where numbered lines != questions + numbered lines kept inside text:", len(count_mismatch))
    for x in count_mismatch[:6]:
        print("  ", x)
    random.seed(args.seed)
    sample = random.sample(pool, args.sample)
    edge = [x for x in pool if x[1]["question_type"] in ("free_text", "dropdown", "multi_choice") ]
    sample += random.sample(edge, min(10, len(edge)))
    out = Path(__file__).resolve().parents[1] / "evidence"
    out.mkdir(exist_ok=True)
    with open(out / "parse_spot_check.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file", "section", "question_number", "question_type", "n_options", "options_lettered",
                    "parsed_question_text", "parsed_options", "parsed_trailing", "raw_block"])
        for name, q in sample:
            w.writerow([name, q["section"], q["question_number"], q["question_type"], q["n_options"],
                        q["options_lettered"], q["question_text"][:400],
                        " | ".join(f'{o["letter"]}. {o["text"]}' for o in q["options"])[:600],
                        (q["trailing_text"] or "")[:300], q["raw_block"][:1500]])
    json.dump({"files": len(files), "status": dict(status), "files_with_lost_lines": len(lost_files),
               "count_mismatch_files": len(count_mismatch),
               "count_mismatch_list": [list(x) for x in count_mismatch],
               "lost_lines_list": [[a, b] for a, b, _ in lost_files]}, open(out / "parse_verify.json", "w"), indent=1)
    print("wrote evidence/parse_spot_check.csv with", len(sample), "rows")


if __name__ == "__main__":
    main()
