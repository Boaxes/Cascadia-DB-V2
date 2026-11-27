# 001: Photo-ID Catalogs

**Status:** Decided (2026-11-27, by Brandon, Q-062 and Q-066)
**Phase:** 2
**Spec requirements served:** IND-01 to IND-05, IDET-01 to IDET-07, SRCH-01, SRCH-02, FILT-01 (Individual), SDET-07

## Question

How MnID, and later Bm and ErId, are stored in gold so that a new catalog needs no schema change (IND-04), and how individuals link to survey sightings.

## Options

### A: Two Tables Plus One Column on Samples (Recommended)

- `individual`: one row per animal. Columns:
  - Catalog code (Mn, Bm, Er) and catalog number. The pair is unique.
  - Species, sex, colour category, dead, and the date confirmed dead.
  - `other_ids` (jsonb): every alias, retired number and cross-catalog ID (SPLASH, DFO, HappyWhale and the rest).
  - `extra` (jsonb): whatever else a catalog carries.
- `identification`: one row per time an individual was seen. It holds V1's survey identifications and MnID's photo-ID records together. Columns:
  - Individual, a nullable sighting, date and position.
  - Research group, contributor, sharing status, quality, HappyWhale link, source (survey, or the catalog code), and `extra`.
- MnID samples join the existing `sample` table, with `individual_id` and `extra`.

A new catalog is new rows. Search reads `other_ids`, so a retired or aliased number finds the current whale.

Volumes from the data profile:
- About 22,500 individuals: 10,743 MnID plus V1's 11,802 for every species, before merging the humpbacks both hold.
- About 253,000 identifications: 166,885 MnID plus 86,580 V1.
- 815 aliases and 498 retired-ID rows, all folded into `other_ids`.

### B: Three Tables

The same as A, but MnID's photo-ID records stay in their own `catalog_record` table, apart from survey identifications. Every page that lists where a whale was seen then reads two tables.

### Rejected Earlier

Two other designs were turned down:
- **Five generic tables** (catalog, individual, individual_id, catalog_record, catalog_sample). Brandon judged this too much (Q-062).
- **A set of tables per catalog.** This breaks IND-04.

## Decision

A. Catalog is a column, not a table. Catalog data is read only on the site (Q-049) and changes only through the pipeline.

The link from a photo-ID record to a survey sighting is the nullable `identification.sighting_id`. The pipeline fills it where a record matches a sighting. By date and sighting number, that's 68% of CRC's MnID records.

Follow-up for the pipeline:
- Fold V1's humpback individuals into MnID's by catalog number. 6,633 of 6,915 match.
- Normalise sharing status and position type to controlled values.
