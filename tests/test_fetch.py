import json

from usajq import fetch
from usajq.ids import portal_and_id


def test_portal_and_id():
    assert portal_and_id("https://apply.usastaffing.gov/ViewQuestionnaire/12445428") == ("usastaffing", "12445428")
    assert portal_and_id("https://jobs.monstergovt.com/gsa/vacancy/previewVacancyQuestions.hms?orgId=1&jnum=112336") == ("monster", "112336")
    assert portal_and_id("https://jobs.monstergovt.com/x/ros/rosDashboard.hms?O=5&J=77") == ("monster", "77")
    assert portal_and_id("https://example.com/") == ("other", None)


def test_monster_preview_url():
    u = "https://jobs.monstergovt.com/gsa/nga/ros/rosDashboard.hms?O=12&J=345"
    assert fetch.monster_preview_url(u) == "https://jobs.monstergovt.com/gsa/vacancy/previewVacancyQuestions.hms?orgId=12&jnum=345"
    assert fetch.monster_preview_url("https://jobs.monstergovt.com/gsa/rospost/?O=1&J=2").endswith("orgId=1&jnum=2")
    assert fetch.monster_preview_url("https://example.com/") is None
    assert fetch.monster_preview_url("https://jobs.monstergovt.com/gsa/") is None


GOOD = "Position Title\nX\nAgency\nY\nAnnouncement Number\nZ\n" + "a" * 600


def test_classify_ok_and_not_found():
    assert fetch.classify_text(200, GOOD) == ("ok", "")
    assert fetch.classify_text(404, "gone")[0] == "not_found"
    assert fetch.classify_text(200, "This questionnaire is no longer available")[0] == "not_found"
    assert fetch.classify_text(200, "<shell only>")[0] == "error"


def test_any_refusal_is_blocked():
    assert fetch.classify_text(403, "")[0] == "blocked"
    assert fetch.classify_text(429, "")[0] == "blocked"
    assert fetch.classify_text(200, "Please complete the CAPTCHA to continue")[0] == "blocked"
    assert fetch.classify_text(200, "Access Denied")[0] == "blocked"
    assert fetch.classify_text(200, "Too many requests, slow down")[0] == "blocked"
    assert fetch.classify_text(500, "")[0] == "error"


def test_state_remembers_and_resumes(tmp_path):
    p = tmp_path / "attempts.jsonl"
    s = fetch.State(p)
    assert not s.done("usastaffing", "1")
    s.add("usastaffing", "1", "ok")
    s.add("usastaffing", "2", "not_found")
    s.add("usastaffing", "3", "error")
    s.add("usastaffing", "4", "blocked")
    s2 = fetch.State(p)  # a new process reads the same file
    assert s2.done("usastaffing", "1") and s2.done("usastaffing", "2")
    assert not s2.done("usastaffing", "3")  # one error: try again
    s2.add("usastaffing", "3", "error")
    assert s2.done("usastaffing", "3")  # two errors: stop retrying
    assert not s2.done("usastaffing", "4")  # a block is never "done": a person decides
    assert len(p.read_text().splitlines()) == 5
    assert json.loads(p.read_text().splitlines()[0])["outcome"] == "ok"


def test_daily_budget(tmp_path, monkeypatch):
    from usajq import config

    monkeypatch.setattr(config, "MAX_REQUESTS_PER_DAY", 5)
    s = fetch.State(tmp_path / "a.jsonl")
    assert fetch.todays_budget(s) == 5
    for i in range(3):
        s.add("usastaffing", str(i), "ok")
    assert fetch.todays_budget(s) == 2
    assert fetch.todays_budget(s, limit=1) == 1
    for i in range(3, 9):
        s.add("usastaffing", str(i), "ok")
    assert fetch.todays_budget(s) == 0


def test_breaker_trips_only_when_nothing_has_worked():
    assert not fetch.breaker_tripped({"ok": 0, "not_found": 0, "error": 7, "blocked": 0}, after=8)
    assert fetch.breaker_tripped({"ok": 0, "not_found": 0, "error": 8, "blocked": 0}, after=8)
    assert not fetch.breaker_tripped({"ok": 1, "not_found": 0, "error": 20, "blocked": 0}, after=8)
    assert not fetch.breaker_tripped({"ok": 0, "not_found": 3, "error": 9, "blocked": 0}, after=8)  # a clear "not found" is a real answer
