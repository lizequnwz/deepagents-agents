# Advisor reference source contract

Every match obtains a fresh `AdvisorReferenceSource` from the app factory's
provider. The source yields canonical advisor records and provenance: source
kind, schema version, retrieval time, and optional query ID. This refactor ships
only the packaged synthetic implementation; production Snowflake integration is
provided by injection rather than application storage.

The service streams records once while enforcing the configured row limit and
the eight-field advisor schema. Master CRD, first name, and last name are
required. Blank or duplicate trimmed CRDs, an empty source, invalid records, and
row-limit overflow block matching as reference-unavailable errors.

The canonical SHA-256 is computed from stable JSON serialization of the ordered
fields `CRD_NUMBER`, `FIRST_NAME`, `LAST_NAME`, `FIRM_NAME`, `EMAIL`, `CITY`,
`STATE`, and `ZIP_CODE`. The model never receives reference rows. Records and
indexes are request-local and are neither cached nor persisted.
