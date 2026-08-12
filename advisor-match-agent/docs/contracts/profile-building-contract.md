# Placeholder advisor profile report contract

Profile reporting is always file-driven. Version 1 produces one deterministic
UTF-8 `advisor_profile_report.html` document with a valid shell and empty body.
It does not fetch, infer, or simulate advisor profile content.

The source is a CSV/XLSX containing one confirmed physical CRD column. It may be
a fresh user upload or the generated `advisor_matches.xlsx` passed through the
same mapping endpoint. CRDs are opaque strings: deterministic code trims outer
whitespace, discards blanks, and deduplicates in first-seen order while
preserving leading zeros, punctuation, case, and nonnumeric forms. Master-data
membership is not required.

Generation resends the original bytes and analysis SHA-256. The service checks
the hash, exact worksheet/header/index binding, mapping fingerprint, and row
limit before rendering. The JSON response contains the filename, media type,
HTML, confirmed mapping, source SHA-256, and input/unique/blank/duplicate counts.
No report record or server-side file is created.
