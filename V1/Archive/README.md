# Archive

Retired code, kept for reference. Nothing here runs, and nothing outside this
folder imports from it.

- `ETL/` -- the previous DB167 pipeline: dbt (raw -> dbo -> app), the cleaning
  rules, the hand-written schemas, and the seed lists. Only the raw import
  (`ETL/import_raw.py`) stayed in use.
- `Django/datahealth/` -- the Data Health pages: the dashboard, track files,
  audit log and Users. The section is now Cascadia Admin.
- `TESTS/` -- the tests that ran the dbt rebuild, and those of the archived
  pages.
- `ops/` -- the script that compared a dbt build with the reference copy.
