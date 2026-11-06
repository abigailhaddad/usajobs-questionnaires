from usajq import health

DAY = "2026-11-07"


def att(outcome, n=1, day=DAY):
    return [{"portal": "usastaffing", "id": str(i), "outcome": outcome, "ts": f"{day}T10:00:00+00:00"} for i in range(n)]


def test_healthy_run():
    assert health.check(att("ok", 100) + att("not_found", 5), DAY) == []


def test_no_attempts_is_a_problem():
    p = health.check([], DAY, expected_min_attempts=1)
    assert p and "attempts today" in p[0]


def test_a_block_fails_the_run():
    p = health.check(att("ok", 50) + att("blocked", 1), DAY)
    assert any("refused" in x for x in p)


def test_all_errors_fail_the_run():
    p = health.check(att("error", 30), DAY)
    assert any("every attempt today was an error" in x for x in p)
    assert any("last 30 attempts" in x or "of the last" in x for x in p)


def test_old_blocks_do_not_fail_todays_run():
    old = att("blocked", 1, day="2026-11-01")
    assert health.check(old + att("ok", 50), DAY) == []


def test_parse_share_catches_a_layout_change():
    assert health.check(att("ok", 40), DAY, {"ok": 38, "html_shell": 5}) == []
    p = health.check(att("ok", 40), DAY, {"ok": 5, "no_questions": 35})
    assert any("page layout may have changed" in x for x in p)
    # a small batch is too small to judge
    assert health.check(att("ok", 5), DAY, {"ok": 1, "no_questions": 4}) == []
