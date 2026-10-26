"""Place for message sanitizing (S1-04): sanitize() is called right before each message is written to the database.

In Stage 3 Musa's filter (app/filters/) will be connected here. For now the text is returned as is.
"""


def sanitize(text: str) -> str:
    """Sanitizes the message text. For now returns it unchanged."""
    return text
