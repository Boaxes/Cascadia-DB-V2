# V2 Spec: Raw Ideas

Brandon's own list of what V2 should change from Cascadia DB (V1). It is deliberately loose. Phase 1 turns it into a concrete spec (`docs/spec/spec.md`) through questions, and the agent does not edit this file.

V2 is a large, partial rebuild of the V1 Django application to these new specifications, aiming for clean code. Copying V1 code is allowed, but only after auditing it, so that unnecessary logic is not brought over.

## Schema

- Create a new, optimised schema that integrates MnID, Bm and ErId, which are photo-ID databases that will be imported eventually. **For now, and this is important:** once we agree on a solid schema, we generate mass synthetic data that closely mirrors Cascadia's cleaned data. Do not worry about dbt or the logistics of combining the data yet. Assume what a final "gold" tier would look like, and work from that.
- When exploring the data for analysis, use DuckDB, which is the most efficient path.
- Tune the schema for read performance with indexes, spatial indexes and other optimisations. The database is largely historical, so writes and edits are extremely rare.
- Parquet (DuckLake?) becomes the source of truth for GPS tracks, with a copy of the same GPS data in Postgres/PostGIS. There are extensions for this, but I am not sure of the proper approach. The goal is to replace the current, slow approach of querying CSV files in object storage for track information. The track files will live on the droplet's disk rather than in object storage.
- Better native support for the audit log. The current one is a mess and a strange custom implementation, so this warrants discussion. Ideally there is one place to check and filter changes to tracks, efforts and so on, from humans and from dbt alike, that answers: "over time, how has this record changed, both programmatically and by hand?" Edits must stay reversible. One possible implementation is dbt-style `valid_from` / `valid_to` rows, but I am not sure. We are not building dbt models now, but a later dbt job should plug straight in.

## General Patterns And Code Cleanup

- Use the common Django practice of apps with their own `urls.py`, connected to the main project's URLs.
- Look for implementations that are overcomplicated compared with a simpler setup.
- Never write slop. We will spend time designing a set of tests, hooks and so on that keeps code quality clean. Prefer simple solutions, and Django-native ways or htmx over JavaScript where possible.
- Code should be compartmentalised, have clear names related to what it does, and stay under 500 lines per file.
- Push to git frequently, but never use the Claude attribution.

## Django Website

- Switch from a top bar to a Databricks-style sidebar, with things naturally grouped together.
- Find a quicker mapping solution, as Leaflet suffers on performance. I am thinking of something that supports WebGL.
- Enhanced capabilities for analysis. The work is largely exploration-driven rather than analysis-driven, and the website should be better positioned to let users do basic analysis work outside the browser. I am not sure what the right pattern is, so it warrants discussion. One option is using the mirrored DuckLake tables with DuckDB WASM, so users can write SQL directly (read-only).
- One implementation of tracks, with user customisation in settings. Right now some tracks show raw points, some let you see timeline events, some have gaps, and some have dashed lines: the implementation is a scattered mess. Give users better control over how tracks look on the website.
- User groups and permissions are a mess right now. We need to agree on a simplified model that is easier to understand.
- You decide further features that could be beneficial (propose them; they go in only if approved).
