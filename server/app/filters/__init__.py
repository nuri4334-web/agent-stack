"""Filters (Stage 3-4): secret, personal data and name masking, hidden instruction detection, answer cleaning.

Every rule and detector works on normalize(text). Rule files are pure: no database, network, clock or settings.
A masked value never appears in a log, an error text, an audit event or a test output; only kinds and counts do.
"""
