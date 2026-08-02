# Example cases

- Exact CRD with conflicting email: match the CRD record and warn.
- Unique exact email with differently formatted name: match the email record and warn.
- Exact John Smith with Boston and Northstar evidence: match only the uniquely supported record.
- Fuzzy name without firm/location support: do not auto-match.
- Duplicate source rows: preserve each row and add duplicate-group metadata.
- Firm and address without name, CRD, or email: `No Match / INSUFFICIENT_EVIDENCE`.
