import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from usajq.redact import remove_emails, PLACEHOLDER  # noqa: E402


def test_removes_plain_and_punctuated_addresses():
    text = "Contact jane.doe@cbp.dhs.gov or HELP-DESK@agency.gov, or o'brien@x.org."
    out, n = remove_emails(text)
    assert n == 3
    assert "@" not in out
    assert out.count(PLACEHOLDER) == 3


def test_leaves_text_without_addresses_unchanged():
    text = "Do you have 5 years of experience? @ home is fine; 3 @ 4 pm."
    out, n = remove_emails(text)
    assert n == 0 and out == text
