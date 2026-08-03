# Example cases

- Exact CRD with conflicting email: match the CRD record and warn.
- Unique exact email with differently formatted name: match the email record and warn.
- Exact John Smith with Boston and Northstar evidence: match only the uniquely supported record.
- Fuzzy name without firm/location support: do not auto-match.
- Duplicate source rows: preserve each row and add duplicate-group metadata.
- Firm and location without name, CRD, or email: `No Match / INSUFFICIENT_EVIDENCE`.
- Exact name with `Morgan Stanley` versus `Morgan Stanley, LLC`: legal-suffix normalization makes the firm exact.
- Exact name with `Ed Jones` versus `Edward D. Jones Financial LLC`: the guarded anchored firm wildcard supplies independent firm support.
- Exact name with `Financial Group` versus `Financial Planning Group`: the anchored firm wildcard supplies independent firm support.
- A wildcard firm input shorter than four normalized characters does not supply firm support.
- Fuzzy name plus merely close firm without exact city/state: `Ambiguous Match`.
- Duplicate authoritative email: `Ambiguous Match / NON_UNIQUE_EMAIL`.
