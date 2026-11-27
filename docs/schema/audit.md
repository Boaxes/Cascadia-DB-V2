# Audit by Versioned Rows

How every change is recorded, shown and reversed (decision 004). There is no separate audit table. Every data table keeps one row per version of each record, with who, why and when on the row. The columns are listed in [schema.md](schema.md#versioned-tables).

The examples below are real output from running `scratch/pgcheck/behaviour.sql` against the schema in a throwaway PostgreSQL 18.6 (invented data; times shown in Pacific).

## Rules

1. **A change never updates data in place.** The only update is setting `valid_to` on the version being replaced. Everything else is an insert.
2. **One transaction per action.** Closing the old version and inserting the new one happen together. Every row an action writes shares one `change_id`.
3. **Edits check what the person saw.** The form carries the `version_id` it was opened on. The write closes the current version only `where id = :id and version_id = :seen and valid_to is null`. If no row matches, someone changed the record in the meantime, nothing is saved, and the person sees "This record changed since you opened it." The unique index on current versions backs this up.
4. **Nothing is deleted, ever.** A delete inserts a version with `deleted = true`. Restore inserts a copy of an earlier version.
5. **Any version can be restored,** including one the pipeline wrote (Q-069).

## Example 1: Pipeline Load

The pipeline loads effort 20417 and two sightings as first versions (`change_type = 'load'`), under run `run-41`.

| version_id | legacy_id | species | size | valid_from | valid_to | change_type | changed_by |
|---:|---:|---|---:|---|---|---|---|
| 1 | 120417 | Gray Whale | 3 | 2026-11-30 18:10 | | load | (pipeline) |

**How dbt writes this.** Each gold table is a dbt incremental model (`materialized='incremental'`, `incremental_strategy='append'`):
- It selects source rows whose hashed `id` has no version in gold yet. Loading is incremental and never re-sends a loaded record (Q-065, Q-068), so these are always new records.
- It adds the version columns: `valid_from` = the run's start, `change_type = 'load'`, `change_source = 'pipeline'`, `pipeline_run_id` = the run, `change_id` = one UUID for the run, and `deleted = false`.
- The run also inserts its `gold.pipeline_run` row.
- dbt tests then check every link (for example each current sighting's `daily_effort_id` names a current effort) and the one-current-version rule.

dbt's `snapshot` is not used. It compares the source with the current row and would undo site edits on every run.

## Example 2: Hand Edit

Sam (user 12) changes sighting 120417 from Gray Whale to Humpback Whale, and the group size from 3 to 2, with the note "Fluke photo shows a humpback".

```sql
begin;
update gold.sighting set valid_to = now() where id = 5001 and version_id = 1 and valid_to is null;
insert into gold.sighting (id, legacy_id, ..., species_id, est_size_best, valid_from,
                           change_type, change_source, changed_by, change_reason, change_id)
select id, legacy_id, ..., 24, 2, now(), 'edit', 'site', 12, 'Fluke photo shows a humpback', :change_id
from gold.sighting where version_id = 1;
commit;
```

| version_id | legacy_id | species | size | valid_from | valid_to | change_type | changed_by | change_reason |
|---:|---:|---|---:|---|---|---|---|---|
| 1 | 120417 | Gray Whale | 3 | 2026-11-30 18:10 | 2026-12-03 09:05 | load | | |
| 3 | 120417 | Humpback Whale | 2 | 2026-12-03 09:05 | | edit | 12 | Fluke photo shows a humpback |

History for sighting 120417 now reads:
- 2026-11-30, Pipeline (run-41): created.
- 2026-12-03, Sam: Species Gray Whale to Humpback Whale; Best Estimate 3 to 2. "Fluke photo shows a humpback".

The field list comes from comparing each version with the one before it, column by column, ignoring the version columns. Only the 50 entries on screen are compared.

## Example 3: Delete With Dependents

Sam deletes effort 20417 with the note "Duplicate of effort 20416". Each current dependent (here, two sightings) gets a deleted version under the same `change_id`, in the same transaction.

| record_table | legacy_id | change_type | deleted | change_id |
|---|---:|---|---|---|
| daily_effort | 20417 | delete | true | …0102 |
| sighting | 120417 | delete | true | …0102 |
| sighting | 120418 | delete | true | …0102 |

`sighting_current` now shows no sightings for the effort. The Audit Log shows one entry for `…0102`, with "Removed With It: 2 sightings" (AUD-03). The dependents of an effort are its sightings, conditions, events and track, and a sighting's samples, sighting events, other species, tag deployments and identifications.

## Example 4: Restore

Alex (user 15) restores the delete with the note "Not a duplicate after all". For every record under `…0102`, the version before the delete is copied in as the new current version, under a new `change_id`.

| version_id | legacy_id | species | size | valid_from | valid_to | deleted | change_type | changed_by |
|---:|---:|---|---:|---|---|---|---|---|
| 1 | 120417 | Gray Whale | 3 | 2026-11-30 18:10 | 2026-12-03 09:05 | false | load | |
| 3 | 120417 | Humpback Whale | 2 | 2026-12-03 09:05 | 2026-12-04 01:00 | false | edit | 12 |
| 4 | 120417 | Humpback Whale | 2 | 2026-12-04 01:00 | 2026-12-05 02:00 | true | delete | 12 |
| 6 | 120417 | Humpback Whale | 2 | 2026-12-05 02:00 | | false | restore | 15 |

Both sightings show again. Sam's edit survives, because the restore copied the version before the delete, which already held the edit. Restoring version 1 instead would put Gray Whale back, as one more version.

## Example 5: Guards

Each of these was refused:

| Attempt | Refused by |
|---|---|
| A second current version of sighting 5001 | `sighting_current_id` (unique `id` where `valid_to is null`) |
| A site edit that names no person | check `(change_source = 'site') = (changed_by is not null)` |
| A second track on effort 20417 | `track_one_per_effort` (TFM-06) |

## Tracks

A track's metadata versions work like any other record. Each version names `ducklake_snapshot_id`, the DuckLake snapshot holding its points, so restoring a track version also restores its points (by time travel, [ducklake.md](ducklake.md#write-path)). The Track File Manager's History lists the `gold.track` versions and can load the points of any of them (TFM-04).

## Where It Shows

| Place | Reads |
|---|---|
| Audit Log page (AUD) | `gold.change_log`, newest first, one entry per `change_id`. Filters: record (table and legacy ID), Who (`changed_by`, or Pipeline for `change_source = 'pipeline'`), Change type, date range. |
| History on a record page (HIST-03) | That record's versions by `id`, in time order: pipeline load, then edits, deletes and restores. |
| Restore This Version | A button on any version, in History and the Audit Log, for Audit Manager and Admin (decision 006, `manage_audit`). |

## Spec Changes This Needs

The frozen spec describes Undo by deletion. CR-001 lists the changes:
- AUD-04: Restore writes a new version, and nothing is deleted.
- AUD-05: pipeline versions can be restored too.
- AUD-02 and HIST-01 to HIST-03: every version is listed.
- EDIT-06 and TFM-08: a delete is put back by restoring.
