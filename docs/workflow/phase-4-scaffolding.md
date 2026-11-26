# Phase 4: Scaffolding

**Goal:** a running, empty shell where every approved decision is already in force: the stack, the schema, synthetic data, DuckLake, and every quality gate. Phase 5 then only adds features.

**Writes:** the repository, except frozen Phase 1 to 3 outputs and protected files. `.claude/settings.json` may now change, but the phase gate hook must stay in it.
**Branch:** `phase-4-scaffolding`.
**Builds on:** the approved spec, the schema documents and the quality documents. Implement them as written. Anything that does not work as written becomes a change request.

## What To Build

1. **Project layout and dependencies:** managed with uv (`pyproject.toml` and the lock file). The Django project has one app per the style guide. Each app has its `urls.py` and an empty landing view, so the sidebar works with nothing behind it.
2. **Settings from the environment:** `DATABASE_URL` and the other settings come from environment variables, so the same code runs in Docker, natively and on the server. Commit `.env.example`. Never commit `.env`.
3. **Docker stack (in git):** `docker-compose.yml` with PostGIS 18 and the web app, matching V1's images where that makes sense, plus a volume for DuckLake data. This is what CI runs. Brandon cannot run Docker on his machine, so CI is how it gets proven.
4. **Native Windows setup (`local/`, gitignored, never committed):** a README and PowerShell scripts to:
   - install PostGIS into the existing PostgreSQL 18 (Stack Builder or the EDB PostGIS bundle; Brandon runs the installer himself);
   - create the database and role;
   - create the uv virtual environment;
   - load the synthetic data;
   - start the site.
   Check that `.gitignore` excludes `local/` before writing anything there.
5. **Database:** migrations that produce exactly the approved `schema.sql` (indexes, spatial indexes and materialized views included), plus the approved audit mechanism. Add a test that compares the migrated schema with `schema.sql`.
6. **DuckLake:** the approved layout, the track write path and the sync to PostGIS, run against synthetic tracks.
7. **Synthetic data generator:** deterministic (seeded), with a `small` size for tests and a `full` size for performance work, reproducing `synthetic-data-profile.md`. It writes Postgres rows and DuckLake track files. It never reads from the live databases. Add tests that check the generated data against the profile's distributions.
8. **Quality gates:** every gate in `quality-gates.md`, at the stated thresholds: Claude hooks in `.claude/settings.json`, commit checks in `.githooks/pre-commit.d/`, and CI in `.github/workflows/`. Prove each gate works by showing it fail on a planted violation and then pass, and record that in the review document.
9. **CI and CD:** CI runs on every pull request. Deployment is **not** automatic. V1 deploys every push to `main` straight to the live droplet, and V2 must not do that until Brandon decides how V2 goes live. Propose the deploy path (new droplet or the same one, and when) in the review document, and ask.

## Review Document

Write `docs/scaffolding-review.md` for Brandon. It covers: how to run the site natively (step by step, in PowerShell), what to look at, the result of every gate with its planted-failure proof, the data generator's comparison with the profile, timings for the heaviest spec queries on full-size data, the CI run link, the deploy proposal, and anything that does not match the approved documents.

## Exit Checklist

- [ ] The site starts natively on Brandon's machine and in CI's Docker, with an empty sidebar shell and synthetic data loaded.
- [ ] The migrated schema matches `schema.sql`. The audit mechanism has been shown on an edit and a revert.
- [ ] DuckLake tracks are written, synced to PostGIS and readable.
- [ ] Every gate is wired in and proven, and CI is green on the pull request.
- [ ] `local/` is not in git, and there are no secrets in git.
- [ ] `docs/scaffolding-review.md` is complete. Brandon has run it locally and asked for any changes.
- [ ] STATUS.md updated, the branch pushed, and Brandon asked to approve.
