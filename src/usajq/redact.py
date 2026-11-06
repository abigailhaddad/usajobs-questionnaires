"""Remove email addresses from questionnaire text before it is parsed or published."""
import re

EMAIL = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
PLACEHOLDER = "[email removed]"


def remove_emails(text: str) -> tuple[str, int]:
    """Return the text with every email address replaced, and how many were replaced."""
    return EMAIL.subn(PLACEHOLDER, text)
