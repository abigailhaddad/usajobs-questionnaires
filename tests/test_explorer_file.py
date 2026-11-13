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


def bad_request(text):
    from huggingface_hub.errors import BadRequestError

    e = BadRequestError.__new__(BadRequestError)  # skip the constructor, which wants an HTTP response
    Exception.__init__(e, text)
    return e


class FakeApi:
    def __init__(self, errors):
        self.errors, self.calls = list(errors), 0

    def create_commit(self, **kw):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


LFS = "Bad request for commit endpoint: Your push was rejected because an LFS pointer pointed to a file that does not exist."


def test_commit_retries_the_missing_lfs_pointer_error():
    api, waits = FakeApi([bad_request(LFS), bad_request(LFS)]), []
    assert exp.commit_with_retry(api, lambda: [], "m", waits=(1, 2, 3), sleep=waits.append) == "ok"
    assert api.calls == 3 and waits == [1, 2]


def test_commit_gives_up_after_the_last_wait():
    import pytest

    api, waits = FakeApi([bad_request(LFS)] * 4), []
    with pytest.raises(Exception, match="LFS pointer"):
        exp.commit_with_retry(api, lambda: [], "m", waits=(1, 2, 3), sleep=waits.append)
    assert api.calls == 4 and waits == [1, 2, 3]


def test_commit_does_not_retry_other_errors():
    import pytest

    api, waits = FakeApi([bad_request("some other bad request")]), []
    with pytest.raises(Exception, match="some other"):
        exp.commit_with_retry(api, lambda: [], "m", waits=(1, 2, 3), sleep=waits.append)
    assert api.calls == 1 and waits == []
