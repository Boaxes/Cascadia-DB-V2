# Phase 3: Quality Gates

**Goal:** agree on the checks that keep AI-written Django clean, before any of it is written. This phase **decides** the gates. Phase 4 wires them in.

**Writes:** `docs/quality/`, plus the workflow logs and `scratch/`.
**Branch:** `phase-3-quality`.

## What To Produce

### `docs/quality/quality-gates.md`

Organise the gates by where they run. Each gate needs: what it catches, the tool and its exact configuration or threshold, how long it takes, and whether it blocks or warns. Every gate must work in both the Docker setup and the native Windows setup, and must skip `V1/` (the read-only copy of V1).

1. **While the agent writes** (Claude Code hooks): fast checks on the file just written, for example format and lint for that file, the 500-line limit, and banned patterns.
2. **Before each commit** (scripts in `.githooks/pre-commit.d/`, run after the phase gate).
3. **In CI** (GitHub Actions on every pull request, in Docker with PostGIS): the full suite.

Candidates to weigh, as a starting list rather than decisions. Propose a set, explain each one, and ask:

- ruff for lint and format, with the rule sets named (including complexity limits).
- A line limit per file (500), and per function if wanted.
- djLint for templates.
- `manage.py check`, `makemigrations --check`, and a migration lint.
- pytest-django with a coverage floor. Every spec requirement ID cited by at least one test.
- import-linter contracts between Django apps.
- Type checking (mypy or pyright), and how strict.
- Dead-code detection (vulture) and security checks (bandit, pip-audit).
- Anti-slop checks: no broad `except`, no `print`, no commented-out code, no TODO without an issue, no new JavaScript or front-end dependency without approval, no em dashes in UI text.
- End-to-end tests for key pages (for example Playwright), and a visual comparison with the `docs/ui/` screenshots. Weigh the cost honestly.
- Query performance checks against the full-size synthetic data for the spec's heaviest pages (for example a query count and a time budget per page).

### `docs/quality/style-guide.md`

These are the Django conventions the code must follow, decided with Brandon. They cover:

- The project layout and app boundaries (one app per sidebar group, or another split), and each app's `urls.py`.
- Views (function-based or class-based, and when to use each), where query logic lives, and when a service module is justified.
- htmx patterns (partials, naming, where swaps happen), and the rule for when JavaScript is allowed.
- Naming, settings, logging and error handling.
- Tests: layout, factories built on the synthetic generator, and what a test must prove.

Keep each rule short, give one example where it helps, and drop any rule that cannot be checked or reviewed.

### `docs/quality/definition-of-done.md`

This is the checklist each Phase 5 feature must pass before it counts as done: spec IDs covered by tests, every gate green, the page matching its screenshot, the work checked in the browser preview, and no change to frozen documents without a change request.

## Exit Checklist

- [ ] The three documents, each gate with a configuration or threshold.
- [ ] Every candidate gate either chosen or rejected with a reason, and Brandon's choices logged.
- [ ] Each gate confirmed to run on Windows natively and in Docker (state how, for each one).
- [ ] STATUS.md updated, the branch pushed, and Brandon asked to approve.
