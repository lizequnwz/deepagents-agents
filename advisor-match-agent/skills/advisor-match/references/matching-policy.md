# Matching policy

Apply rules in order:

1. Exact master CRD is decisive; record other conflicts as warnings.
2. A unique exact normalized email matches; CRD still takes precedence.
3. Exact normalized name requires independent firm or location support.
4. A fuzzy name requires independent support, policy acceptance, and runner-up separation.
5. Plausible but unresolved candidates are `Ambiguous Match`; choose none.
6. Invalid, insufficient, or unsupported rows are `No Match` with a reason.
7. User-confirmed decisions are `Matched / User Confirmed` and retain the automated result.

Never confirm name-only or firm/address-only identity. Blank values never match blanks. Nickname aliases generate candidates only.

Numeric scores are internal policy scores, not probabilities, and must not be presented to the user.
