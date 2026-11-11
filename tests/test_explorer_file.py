import importlib.util
from pathlib import Path

import duckdb
import pandas as pd

spec = importlib.util.spec_from_file_location("exp", Path(__file__).parents[1] / "scripts" / "build_explorer_file.py")
exp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exp)


def part(tmp, name, ids, extra=None):
    rows = [{"portal": "usastaffing", "questionnaire_id": i, "n_questions": 3, "raw_text": "long text " + i,
             "usajobs_control_numbers": ["1", "2"]} for i in ids]
    df = pd.DataFrame(rows)
    if extra:
        df[extra] = "x"
    p = tmp / name
    df.to_parquet(p)
    return str(p)


def test_combines_parts_and_drops_raw_text(tmp_path):
    # a later part with an extra column, as union_by_name allows
    srcs = [part(tmp_path, "a.parquet", ["1", "2"]), part(tmp_path, "b.parquet", ["3"], extra="hiring_agency")]
    out = tmp_path / "out" / "q.parquet"
    problems, facts = exp.build(srcs, out)
    assert problems == []
    assert facts["rows"] == 3 and facts["row_groups"] == 1
    cols = [r[0] for r in duckdb.connect().execute(f"describe select * from '{out}'").fetchall()]
    assert "raw_text" not in cols and "hiring_agency" in cols
    assert duckdb.connect().execute(f"select usajobs_control_numbers from '{out}' limit 1").fetchone()[0] == ["1", "2"]


def test_repeated_id_across_parts_is_a_problem(tmp_path):
    srcs = [part(tmp_path, "a.parquet", ["1"]), part(tmp_path, "b.parquet", ["1"])]
    problems, _ = exp.build(srcs, tmp_path / "q.parquet")
    assert any("repeat" in p for p in problems)
