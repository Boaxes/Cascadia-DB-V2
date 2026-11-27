# 002: Primary Keys

**Status:** Decided (2026-11-27, by Brandon, Q-063)
**Phase:** 2
**Spec requirements served:** EDET-01, SDET-01, SRCH-01, HIST-02, and every URL in the spec's URL map

## Question

What identifies each record in gold, and which ID people see and type.

## Options

### A: Hashed Keys, as V1 (Recommended)

- **Survey records** (efforts, sightings, conditions, events, samples, identifications, sighting events and other species) are keyed by a 64-bit hash of their natural key, for example (research group, vessel, date, sighting number) for a sighting. This is V1's `key_hash`.
  - The key is the same on every load and survives DB167 renumbering, so versions and links stay attached.
  - The DB167 ID is kept as `legacy_id`. People see and type it ("Sighting 120417"), and URLs use it, as in V1.
- **Lookup tables** keep the IDs the pipeline assigns, because nothing renumbers them.
- **Catalog individuals** are keyed by a hash of (catalog, catalog number), so every version of a whale shares one key (decision 004). They display as catalog plus number (CRC-20417), and their URL is `/individuals/mn-20417/`. This detail was settled while writing the schema, and is listed for Brandon's review.

### B: Postgres Identity Keys

Postgres assigns numbers, and every load maps source rows back to them through a lookup table. This is more pipeline work for the same result.

### C: DB167 IDs as Primary Keys

This is the simplest, but DB167 renumbers records, so links and history would break. V1 moved away from it for this reason.

## Decision

A. Human keys repeat in the source (205 sighting pairs, 2 effort pairs), so V1's rule carries over: the lowest legacy ID keeps the plain hash, and the others add their legacy ID to the hash.

`legacy_id` is unique within each table and is what URLs resolve.

In the versioned tables (decision 004), the hashed `id` names the record and is shared by all of its versions. Each version row also has its own `version_id`.
