# Advisor schema

The authoritative matching snapshot is ordered as:

`CRD_NUMBER, FIRST_NAME, LAST_NAME, FIRM_NAME, EMAIL, CITY, STATE, ZIP_CODE`

Street address is outside this workflow. ZIP is retained as display-only context and does not affect scoring, support, or conflicts. Treat CRD and ZIP as strings. Master CRD, first name, and last name are required; other fields may be blank. Reject an empty source, missing columns, malformed or duplicate master CRDs, or a reference row-limit overflow.

An input mapping may bind CRD, full name or both first/last name, firm, email, city, state, and optional ZIP. A headed mapping binds every field by zero-based position and exact observed header; position disambiguates duplicate headers. A headerless mapping uses the exact position with `header=null`.
