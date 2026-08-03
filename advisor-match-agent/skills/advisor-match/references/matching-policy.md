# Matching policy

Apply rules in order:

1. Exact master CRD is decisive; record other conflicts as warnings.
2. A unique exact normalized email matches; CRD still takes precedence. A non-unique authoritative email is `Ambiguous Match`.
3. A usable name is a full name with at least two meaningful parts or both first and last name.
4. Exact normalized name requires independent firm or exact city-and-state support.
5. Legal firm suffixes are normalization-only. A close firm may support an exact name. An anchored firm wildcard inserts `%` between user-supplied words and at the end, so `Ed Jones` may support `Edward D. Jones Financial LLC`; normalized wildcard inputs shorter than four characters are not support. A fuzzy name plus fuzzy firm cannot auto-match without exact city and state.
6. Strong firm or state conflicts block name-based auto-matching. Same-state city differences are warnings and do not block an exact-name plus strong-firm result.
7. A fuzzy name requires independent support, policy acceptance, and runner-up separation.
8. Plausible but unresolved candidates are `Ambiguous Match`; choose none.
9. Invalid, insufficient, or unsupported rows are `No Match` with a row-level reason.
10. User-confirmed decisions are `Matched / User Confirmed` and retain the automated status in the audit fields.

Never confirm name-only, nickname-only, or firm/location-only identity. Blank values never match blanks. ZIP is contextual only. Numeric scores are internal policy thresholds, not probabilities, and must not be presented to the user.
