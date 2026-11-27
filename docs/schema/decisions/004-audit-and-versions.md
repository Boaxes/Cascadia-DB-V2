# 004: Audit by Versioned Rows

**Status:** Decided (2026-11-27, by Brandon, Q-064, Q-065, Q-067, Q-068, Q-069)
**Phase:** 2
**Spec requirements served:** HIST-01 to HIST-04, AUD-01 to AUD-05, EDIT-04, EDIT-06, TFM-05, TFM-08 (several change through CR-001)

## Question

How the site answers "how has this record changed over time, by hand and by the pipeline?" in one place, keeps every change reversible, and accepts a later dbt job without rework.

## Options

### A: One `audit_entry` Table (V1's Model)

Each entry holds a field-level diff (old and new values), and Undo deletes the entry. Brandon chose against this.

### B: django-pghistory

Triggers fill a per-model event table. Pipeline reloads would flood it, and Undo is still custom code.

### C: django-simple-history

It runs in Python only, so it never sees pipeline writes.

### D: Versioned Rows, valid_from and valid_to, With Who and Why (Chosen)

Every version of a record is a row. Nothing is ever deleted.

## Decision

D, with these rules.

**Columns on every data table except the lookups** (efforts, sightings, conditions, events, sighting events, other species, tag deployments, individuals, identifications, samples, track metadata):
- `version_id` (identity) and `id` (the hashed record key, decision 002).
- `valid_from` and `valid_to` (null on the current version).
- `changed_by` (a user, or null for the pipeline) and `change_source` (site or pipeline).
- `change_reason` (the person's note, or the pipeline run) and `change_id` (shared by every row one action writes).
- `deleted` (true on a version that removes the record).

**Layout:** all versions live in one table per record type, with a `<table>_current` view (`valid_to is null and not deleted`). Links between tables point at the record key `id`, so dbt tests check them in place of foreign keys (Q-067).

**How each change is written:**
- **Edit:** in one transaction, close the current row (`valid_to = now()`) and insert a copy carrying the new values, who and why.
- **Delete:** insert a version with `deleted = true` for the record and for each dependent record, all under one `change_id`.
- **Restore:** insert a copy of any earlier version, including one the pipeline wrote (Q-069), as the new current version. Restoring a delete restores every record under its `change_id`.
- **Pipeline:** loading is incremental and only loads data not loaded before (Q-065, Q-068). dbt writes each new record as its first version, with `change_source = 'pipeline'` and the run in `change_reason`. It never rewrites an existing record, so a person's edit is never overwritten and no conflict rule is needed.

**Tracks:** point versions come from DuckLake snapshots (decision 003). The track metadata row records who and why.

**Where it shows:**
- The Audit Log page lists versions across tables, grouped by `change_id`.
- A record's History lists its versions in time order.

**dbt integration:** each gold table is a dbt incremental model with `unique_key = version_id` and an append-only strategy that inserts first versions of new records. dbt's own `snapshot` is not used, because it compares the source with the current row and would undo site edits.

Follow-up: the spec changes in CR-001 (AUD-02, AUD-04, AUD-05, HIST-01 to HIST-03, EDIT-06, TFM-08). Worked examples are in `audit.md`.
