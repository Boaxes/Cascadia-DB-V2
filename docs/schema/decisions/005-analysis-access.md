# 005: Analysis Access for the SQL Page

**Status:** Decided (2026-11-27, by Brandon, Q-073, Q-074)
**Phase:** 2
**Spec requirements served:** SQL-01 to SQL-03, EXP-03

## Question

Which data the in-browser SQL page (DuckDB WASM) gets, in what form, and how it is kept current.

## Options

### A: Current Rows, Track Lines and Points by Year (Chosen)

- **Files:**
  - One Parquet file per `_current` view.
  - Track lines at the 11 m level, with WKT geometry.
  - GPS points split into one file per year.
- **Serving:** files are served to signed-in users only, with HTTP range requests, so DuckDB WASM fetches only the row groups a query reads. A query over one year of points downloads about 10 MB, not the 116 MB total.
- **Refresh:** a job rewrites a table's file after each pipeline load, and within a minute of a site edit to that table.

### B: As A, Plus Every Version

This adds queries about history. Versions are rare today, so the extra size is small, but it grows with every edit. Not chosen.

### C: Current Rows and Lines Only

Points would be available through Export only. Not chosen.

## Decision

A. Phase 4 builds:
- The export job, written in DuckDB, reading Postgres and the DuckLake points.
- The serving view: Django checks the login, then hands the file to the web server for range-request serving.

The audit columns stay in the exported current rows. Login and user tables are never exported.
