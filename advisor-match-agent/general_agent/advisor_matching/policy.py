"""Versioned matching-policy defaults."""

POLICY_VERSION = "1"
ACCEPTANCE_SCORE = 0.92
PLAUSIBLE_SCORE = 0.78
MINIMUM_MARGIN = 0.10
MINIMUM_NAME_SIMILARITY = 0.92
REVIEW_CANDIDATE_LIMIT = 3
WEIGHTS = {"name": 0.50, "firm": 0.20, "street": 0.12, "city": 0.06, "state": 0.06, "zip": 0.06}
