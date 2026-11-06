from pathlib import Path

from usajq.parse_usastaffing import _footer_start, parse, text_hash

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return parse((FIX / name).read_text(encoding="utf-8"))


def kinds(r):
    return [(q["section_kind"], q["question_number"], q["question_type"], q["n_options"]) for q in r["questions"]]


def test_header_fields_and_dates():
    r = load("format_a_inline_numbers.txt")
    assert r["parse_status"] == "ok"
    assert r["position_title"] == "Recreation Specialist - Programmer"
    assert r["announcement_number"] == "22-11663648"  # "Opens in new window" is stripped
    assert r["open_date"] == "2022-12-22" and r["close_date"] == "2023-01-05"
    assert r["preview_banner"] is True


def test_sections_in_page_order():
    r = load("format_a_inline_numbers.txt")
    assert [s["section"] for s in r["sections"]] == ["Eligibilities", "Preferences", "Assessment 1"]
    assert [s["section_kind"] for s in r["sections"]] == ["eligibility", "preference", "assessment"]


def test_lettered_choices_and_numbers_inline():
    r = load("format_a_inline_numbers.txt")
    first = r["questions"][0]
    assert first["question_text"] == "Do you claim Veterans’ Preference?"
    assert first["n_options"] == 7 and first["options_lettered"] is True
    assert first["options"][0] == {"letter": "A", "text": "No, I do not claim Veterans' Preference"}
    assert len(r["questions"]) == 13


def test_number_on_its_own_line_and_unlettered_choices():
    r = load("format_b_numbers_alone.txt")
    assert len(r["questions"]) == 6
    q = r["questions"][0]
    assert q["question_text"].startswith("Are you a current National Guard member")
    assert [o["text"] for o in q["options"]] == ["Yes", "No"]
    assert q["options_lettered"] is False
    assert [o["letter"] for o in q["options"]] == ["A", "B"]  # numbered in page order


def test_text_between_questions_is_kept_as_trailing_text_not_lost():
    r = load("format_b_numbers_alone.txt")
    # The "Select Yes or No" note and the example paragraphs sit between questions.
    joined = "\n".join(q["question_text"] + "\n" + (q["trailing_text"] or "") for q in r["questions"])
    assert "Does your resume reflect both month and year?" in joined


def test_free_text_question_has_no_choices():
    r = load("free_text.txt")
    free = [q for q in r["questions"] if q["question_type"] == "free_text"]
    assert len(free) == 1
    assert free[0]["question_text"] == "What tools have you used to measure the success of a program?"
    assert free[0]["n_options"] == 0


def test_dropdown_question():
    r = load("dropdown.txt")
    assert r["questions"][0]["question_type"] == "dropdown"
    assert r["questions"][0]["trailing_text"]  # the dropdown's entries are kept as text


def test_block_may_start_at_a_number_above_one():
    r = load("start_not_1.txt")
    pref = [q for q in r["questions"] if q["section_kind"] == "preference"]
    assert [q["question_number"] for q in pref] == [2]
    assert len(r["questions"]) == 12


def test_footer_is_not_part_of_any_question():
    for name in ("format_a_inline_numbers.txt", "free_text.txt", "dropdown.txt"):
        r = load(name)
        everything = "\n".join(q["raw_block"] for q in r["questions"])
        assert "Terms of Use" not in everything and "USA Staffing® System" not in everything


def test_every_body_line_is_kept_somewhere():
    for name in ("format_a_inline_numbers.txt", "format_b_numbers_alone.txt", "start_not_1.txt"):
        r = load(name)
        blob = "\n".join(q["raw_block"] for q in r["questions"]) + "\n".join((s["intro_text"] or "") for s in r["sections"])
        text = (FIX / name).read_text(encoding="utf-8").split("\n")
        end = _footer_start(text)
        for line in text[9:end]:
            s = line.strip()
            if s and not s.startswith("For preview") and s not in ("Eligibilities", "Preferences", "Conditions of Employment") and not s.startswith("Assessment "):
                assert s in blob, (name, s)


def test_question_ids_are_not_needed_to_be_unique_but_ordinals_are_in_order():
    r = load("dropdown.txt")
    assert [q["question_number"] for q in r["questions"]][:3] == [1, 1, 2]  # a block can restart at 1


def test_html_shell_and_login_pages_are_labelled_not_parsed():
    assert parse("<!DOCTYPE html>\n<html><body>x</body></html>")["parse_status"] == "html_shell"
    login = "An official website of the United States government Here's how you know\nsomething"
    assert parse(login)["parse_status"] == "login_page"
    assert parse("hello world")["parse_status"] == "not_a_questionnaire"


def test_empty_questionnaire():
    text = ("Position Title\nCASHIER\nAgency\nAir Force\nAnnouncement Number\nX1 Opens in new window\n"
            "Open Period\nThursday, July 17, 2025 to Wednesday, July 30, 2025\n"
            "For preview purposes only. To apply, please return to the USAJOBS announcement.\n"
            " Terms of Use\n FOIA\nPrivacy & Cookies\n")
    r = parse(text)
    assert r["parse_status"] == "no_questions" and r["questions"] == []
    assert r["announcement_number"] == "X1"


def test_text_hash_is_stable():
    assert text_hash("a") == text_hash("a") and text_hash("a") != text_hash("b")
