# Matching policy

Apply rules in order:

1. Exact master CRD is decisive; record other conflicts as warnings.
2. A unique exact normalized email matches; CRD still takes precedence. A non-unique authoritative email is `Ambiguous Match`.
3. A usable name is indexed by exact normalized first and last name. Separate fields preserve the complete last-name field. Uncommaed full names use the first and last tokens, ignoring middle tokens; therefore an uncommaed compound surname may require CRD, email, split columns, or review correction.
4. Exact normalized first and last name requires independent firm or exact city-and-state support.
5. Legal firm suffixes are normalization-only. A close firm may support an exact name. An anchored firm wildcard inserts `%` between user-supplied words and at the end, so `Ed Jones` may support `Edward D. Jones Financial LLC`; normalized wildcard inputs shorter than four characters are not support.
6. Strong firm or state conflicts block name-based auto-matching. Same-state city differences are warnings and do not block an exact-name plus strong-firm result.
7. General fuzzy-name matching is not supported. Curated nickname mappings produce review-only candidates even when other evidence supports them.
8. Exact-name or nickname candidates that cannot be uniquely automated are `Ambiguous Match`; choose none. At most three are displayed together with the total candidate count and a truncation flag.
9. Invalid, insufficient, or unsupported rows are `No Match` with a row-level reason.
10. User-confirmed decisions are `Matched / User Confirmed` and retain the automated status in the audit fields.

Never confirm name-only, nickname-only, or firm/location-only identity. Blank values never match blanks. ZIP is contextual only. Firm similarity is evaluated only within the bounded exact-name candidate group and is not presented as a score.
