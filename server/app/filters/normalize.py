"""Normalize (S3-01): removes invisible characters before every rule and detector.

An attacker could hide a key from the rules with an invisible character ("xo​xb-..."); after normalize the
rules see the plain key. Visible text, letter case and line breaks are not changed.
"""
import re

# Zero-width and joiner characters, direction marks and embeddings, word joiner and invisible operators, BOM.
# Note: U+200D (zero-width joiner) is in the range, so an emoji sequence joined by it splits into its parts.
_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤﻿]")


def normalize(text: str) -> str:
    """The text without the invisible characters U+200B-U+200F, U+202A-U+202E, U+2060-U+2064 and U+FEFF."""
    return _INVISIBLE.sub("", text)
