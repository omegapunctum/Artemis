# ARTEMIS Data Contract

## coordinates_source

Allowed values (curated Airtable enum + ETL allowlist):

- UNESCO
- Britannica
- Official Site
- Vatican
- Pompidou Site
- Wikipedia
- PBS
- Dezeen
- Saylor

## Synchronization Rule

Airtable enum **MUST** be synchronized with ETL allowlist.

Adding a new `coordinates_source` value in Airtable requires updating ETL allowlist/normalization first; otherwise records with the new value will be rejected as `invalid_coordinates_source`.
