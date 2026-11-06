import importlib.util
from pathlib import Path

import pandas as pd

spec = importlib.util.spec_from_file_location("pub", Path(__file__).parents[1] / "scripts" / "publish_to_hf.py")
pub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pub)


def write(tmp, qn, k, s=None):
    pd.DataFrame(qn).to_parquet(tmp / "questionnaires.parquet")
    pd.DataFrame(k, columns=["question_id", "questionnaire_id", "portal"]).to_parquet(tmp / "questions.parquet")
    pd.DataFrame(s or [{"questionnaire_id": "1", "portal": "usastaffing"}]).to_parquet(tmp / "sections.parquet")


def good(n=2):
    qn = [{"questionnaire_id": "1", "portal": "usastaffing", "parse_status": "ok", "n_questions": n, "raw_text": "x"}]
    k = [{"question_id": f"1-{i:03d}", "questionnaire_id": "1", "portal": "usastaffing"} for i in range(1, n + 1)]
    return qn, k


def test_good_release_passes(tmp_path):
    write(tmp_path, *good())
    problems, facts = pub.check_release(tmp_path)
    assert problems == [] and facts["questions"] == 2


def test_repeated_ids_and_count_mismatch_fail(tmp_path):
    qn, k = good()
    write(tmp_path, qn + qn, k)
    problems, _ = pub.check_release(tmp_path)
    assert any("ids repeat" in p for p in problems)
    qn, k = good(3)
    write(tmp_path, qn, k[:2])
    problems, _ = pub.check_release(tmp_path)
    assert any("differ from the sum" in p for p in problems)


def test_orphan_question_and_unknown_status_fail(tmp_path):
    qn, k = good()
    k.append({"question_id": "9-001", "questionnaire_id": "9", "portal": "usastaffing"})
    qn[0]["n_questions"] = 3
    write(tmp_path, qn, k)
    assert any("not in the table" in p for p in pub.check_release(tmp_path)[0])
    qn, k = good()
    qn[0]["parse_status"] = "weird"
    write(tmp_path, qn, k)
    assert any("unknown parse_status" in p for p in pub.check_release(tmp_path)[0])


def test_junk_pages_must_not_keep_their_text(tmp_path):
    qn, k = good(0)
    qn[0]["parse_status"] = "html_shell"
    write(tmp_path, qn, k)
    problems, _ = pub.check_release(tmp_path)
    assert any("kept their raw text" in p for p in problems)
