# Advisor schema

The authoritative schema is ordered as:

`CRD_NUMBER, FIRST_NAME, LAST_NAME, FIRM_NAME, EMAIL, STREET_ADDRESS, CITY, STATE, ZIP_CODE`

Treat CRD and ZIP as strings. Master CRD, first name, and last name are required; other fields may be blank. Reject an empty source, missing columns, malformed CRDs, or duplicate CRDs.

An input mapping may bind CRD, first name, last name, full name, firm, email, street, city, state, and ZIP. Bind by both zero-based position and observed header so duplicate headers cannot silently bind incorrectly.
