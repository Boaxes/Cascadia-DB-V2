# Cascadia DB V2

A partial rebuild of the Cascadia DB website (V1) for Cascadia Research Collective: marine mammal survey records (sightings, effort, GPS tracks, samples) plus photo-ID catalogs. V2 follows a new spec, in [V2Spec.MD](V2Spec.MD), which is Brandon's raw list of ideas. Turning that list into something concrete is the first job, not something to assume.

The work runs in five phases, and **each ends with Brandon's written approval**. Do one phase at a time, and never start the next phase's work early, not even as a draft.

| Phase | Produces | Doc |
|---|---|---|
| 1. Spec And Mockup | A concrete spec with testable requirements, and static HTML mockups of every page | [phase-1](docs/workflow/phase-1-spec-and-mockup.md) |
| 2. Schema And DuckLake | The gold-tier Postgres schema, the DuckLake design for GPS tracks, the audit log design, and a profile for the synthetic data | [phase-2](docs/workflow/phase-2-schema-and-ducklake.md) |
| 3. Quality Gates | The agreed hooks, tests, CI checks and style rules that keep AI-written code clean | [phase-3](docs/workflow/phase-3-quality-gates.md) |
| 4. Scaffolding | A running empty shell: Docker and native setup, migrations, synthetic data, DuckLake, every gate wired in, CI | [phase-4](docs/workflow/phase-4-scaffolding.md) |
| 5. Build | The website, page by page, from the spec and the approved screenshots | [phase-5](docs/workflow/phase-5-build.md) |

## Start Of Every Session

1. The SessionStart hook prints the current phase. If it is missing, run `python .claude/hooks/phase_gate.py --status`.
2. Read [docs/workflow/STATUS.md](docs/workflow/STATUS.md) (where the last session stopped) and the current phase's doc. Read the phase doc in full before acting.
3. Continue from STATUS.md. Update it at the end of each working stretch: what was done, what is next, what is waiting on Brandon.

## The Gate

`.claude/hooks/phase_gate.py` runs before every file write and shell command. It enforces the following:

- Each phase writes only its own folders, plus `scratch/` (gitignored working space) and the three workflow logs. Writes outside those are refused.
Once a phase is approved, its outputs are frozen. To change one, add an entry to docs/workflow/change-requests.md that names each file or folder in backticks, and ask Brandon in chat. Once he says yes, record his answer in the entry's Decision field and make the change. The phase stays approved.
- Only Brandon edits [docs/workflow/APPROVALS.md](docs/workflow/APPROVALS.md), this file, `V2Spec.MD`, the phase docs, the gate itself, `Data/` and `V1/`.
- `.env` (live credentials), `Data/export_databases.py` and anything else that touches the live databases are blocked.
- Hooks may not be skipped (`--no-verify` and similar), and the agent never commits, merges or pushes on `main`.

When the gate refuses something, do not look for a way around it. Either the work belongs to another phase, or it needs Brandon. Tell him which.

When a phase's exit checklist is complete, update STATUS.md, summarise what is ready for review, and ask Brandon to approve it by adding `Phase N: Approved <date>` to APPROVALS.md. Never write "approved" anywhere yourself, and never treat a "looks good" in chat as the approval. The line in the file is the approval.

## Asking Questions

The point of Phases 1 to 3 is to remove ambiguity, so **ask rather than guess**.

- Use the question tool (AskUserQuestion). Send up to 4 questions per call, each with 2 to 4 concrete options. Put the recommended option first and label it "(Recommended)". Expect several rounds.
- Before every question call, write out in the message itself what Brandon needs in order to decide: the findings, every option, what each one covers and costs, with real links. The question box can hide earlier text.
- Ask about one decision per question. Make it concrete: "Should the Sightings list default to the current year or all years?", not "Any thoughts on filters?".
- Record every question and answer in [docs/workflow/questions-log.md](docs/workflow/questions-log.md) as soon as it is answered.
- If you must proceed on an assumption, write it down as an assumption, list it at the next review, and get it confirmed before the phase closes.

## Sources

- **`Data/`** holds read-only Parquet snapshots taken 2026-11-26. Read [Data/README.md](Data/README.md) first. Explore with DuckDB (`python -c "import duckdb"`, version 2.x). `Postgres/app` is what the V1 website reads, `Postgres/dbo` is the cleaned DB167, `SQLServer/dbo` is raw DB167, and `MnID/` is the humpback photo-ID catalog (an Access database).
- **Bm** (blue whale) and **ErId** (gray whale) catalogs are not provided yet. Assume they are shaped like MnID, and design so a third or fourth catalog needs no schema change.
- **V1** is in [`V1/`](V1/): a read-only copy of Cascadia DB as committed at `f4b2a36` (2026-09-29), the version live today. Start with [V1/README.md](V1/README.md), then `V1/Django` (the website: the `survey` and `admintools` apps), `V1/ETL` (the dbt pipeline and schema SQL) and `V1/docs`. V1's README and deploy workflow describe how V1 runs, and none of that applies to V2. Every tool (lint, tests, Django) must ignore `V1/`. V1 code may be copied only after auditing it line by line. Say in the commit what was copied and what was cut. V1 has known sprawl: `survey/views.py` is 778 lines, the audit log is custom, and track display is scattered.
- Never connect to the live Postgres or SQL Server. Everything needed is in `Data/`, and synthetic data replaces it from Phase 4 on.

## Environment

- **This machine:** Windows, no Docker (virtualization is off). It has Python 3.13, uv, DuckDB 2.x, and native PostgreSQL 18 running as a service, but **PostGIS is not installed yet** (Phase 4 adds it). Edge and Chrome are available for headless screenshots.
- **In git:** Docker Compose is the supported stack, and it is what CI runs. The native Windows setup for Brandon's machine lives in `local/`, which is gitignored and never committed.
- The shell is Git Bash. Give Brandon commands to run in PowerShell.

## Git

- Work on one branch per phase (`phase-1-spec`, `phase-2-schema`, `phase-3-quality`, `phase-4-scaffolding`, `phase-5-<feature>`). Commit often, with plain messages that say what changed. Push the branch.
- Nothing merges to `main` until Brandon has previewed the work running locally. He merges.
- No Claude attribution in commits or PRs (`.claude/settings.json` turns it off). Do not add it by hand.

## Writing Rules (Everything, Including UI Text, Docs And Comments)

- No em dashes. Use a comma, colon, parentheses or a new sentence. En dashes in ranges (2001–2026) are fine.
- Titles in Title Case: headings, page titles, nav and button labels.
- UI labels name the thing, not whose it is: "Settings", not "My Settings".
- The UI shows restraint. Use the site's own components, put things where Brandon names them, and build no busy dashboards he did not ask for.

## Code Rules (Made Concrete And Enforced In Phase 3)

- Each Django app has its own `urls.py`, included from the project `urls.py`.
- Choose the simplest thing that works. Prefer Django built-ins and htmx over custom JavaScript.
- Files stay under 500 lines. Names say what the code does. No speculative abstractions, no dead code, no commented-out code.
