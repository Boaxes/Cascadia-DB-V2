# Quality Gates

The checks that keep the Unified DB code clean, decided with Brandon in Phase 3 (Q-084 to Q-101). Phase 4 wires them in. Each gate says what it catches, the tool and its setting, how long it takes, and whether it blocks.

Every gate skips `V1/`, `Data/`, `scratch/` and `mockups/`.

## Where the Gates Run

| Moment | How | What runs | Blocks |
|---|---|---|---|
| **After the agent saves a file** | Claude Code `PostToolUse` hook on Edit, Write and MultiEdit | The fast checks, on that one file (under 1 s) | Yes: the agent sees the error and fixes it before moving on |
| **Before the agent ends a turn** | Claude Code `Stop` hook (Q-087) | Every check below on the whole project, then the Haiku review (about 1 to 3 min) | Yes: the agent cannot say it is done until everything is green |
| **Before a commit** | The phase gate (already in place), then `.githooks/pre-commit.d/` | The fast checks on the staged files | Yes |
| **On GitHub after a push** | GitHub Actions on every push and pull request, in Docker Compose with PostGIS (Q-088) | Every check except the Haiku review | Yes: a red run means the branch is not ready to merge |

**Before-done hook details:**
- It runs only when files in the repository changed since the last green run. A turn that only answers a question finishes at once. The last green state is kept in `scratch/.last-green`.
- If the same checks keep failing, it blocks at most 5 times in a row. Then the agent stops and reports the failures as not done, so a stuck check cannot loop forever.

## The Gates

### Fast Checks (After Each Save, at Commit, Before Done, on GitHub)

| Gate | Catches | Tool and setting | Time |
|---|---|---|---|
| **Format** | Inconsistent layout | `ruff format`, line length 120 | under 0.1 s a file |
| **Lint** | Real bugs, risky code and AI leftovers | `ruff check` with the rules listed below | under 0.1 s a file |
| **Templates** | Broken or messy Django templates | `djlint --check` and `djlint --lint`, profile `django`, indent 2 | about 0.5 s a file |
| **One comment per file** (Q-090, Q-093) | Comments that explain unclear code, commented-out code, TODOs, and comments that switch off a check (`# noqa`, `# type: ignore`) | `scripts/check_files.py`: each Python, template, JavaScript and CSS file starts with exactly one comment (a block of consecutive comment lines, or a module docstring) saying what the file is for, and has no other comment. Docstrings on functions and classes are allowed. | under 0.1 s a file |
| **File size** | Files that grow into V1's 700 to 1,000-line modules | `scripts/check_files.py`: at most 500 lines per Python, template, JavaScript and CSS file | under 0.1 s |
| **Writing rules** | CLAUDE.md's rules in code and UI text | `scripts/check_files.py`: no em dash in any file; in templates, no label starting "My " or "Your " | under 0.1 s |

**ruff rules.** `select = ["E", "W", "F", "I", "B", "UP", "N", "SIM", "RET", "DJ", "S", "BLE", "T20", "C90", "PLR0912", "PLR0913", "PLR0915"]`.
- **E, W, F:** errors, warnings and undefined or unused names.
- **I:** import order.
- **B:** likely bugs.
- **UP:** old syntax for Python 3.13.
- **N:** naming.
- **SIM, RET:** needlessly roundabout code.
- **DJ:** Django mistakes, such as a model without `__str__` or `null=True` on text fields.
- **S:** security, the same checks as bandit.
- **BLE:** `except Exception` and bare `except`.
- **T20:** `print`.
- **Complexity:** `mccabe.max-complexity = 10`, `pylint.max-args = 6`, `pylint.max-branches = 12`, `pylint.max-statements = 50`.

### Project Checks (Before Done, on GitHub)

| Gate | Catches | Tool and setting | Time |
|---|---|---|---|
| **Helpers used 3 times** (Q-090, Q-094) | Helper functions written for one or two callers, and functions nothing calls | `scripts/check_reuse.py`. A function in site code must be referenced in at least 3 places outside tests, or the check fails. Exempt: views (named in a `urls.py`), methods on models, forms, admin classes and management commands, template tags and filters, signal receivers, dunder methods, and everything in tests. Matching is by name. | about 1 s |
| **Code repeated 3 times** (Q-090, Q-095) | Copied logic that should be one helper | `scripts/check_repeats.py`. Any block of 5 or more lines (ignoring blank lines and leading spaces) that appears 3 or more times across Python, templates and JavaScript fails. Tests are included, so repeated test setup becomes a fixture. Migrations are skipped. | about 1 s |
| **Types** (Q-084) | Passing the wrong kind of value, wrong attribute names | `mypy` with `django-stubs`: `check_untyped_defs = true`, `warn_return_any = true`, annotations not required. Libraries without type information are listed in the config, since `# type: ignore` is banned. | about 20 to 40 s |
| **Django checks** | Broken settings, missing migrations | `manage.py check --deploy --fail-level WARNING` and `manage.py makemigrations --check --dry-run` | about 3 s |

### Tests (Before Done, on GitHub)

| Gate | Catches | Tool and setting | Time |
|---|---|---|---|
| **Tests** | Behaviour that does not match the spec | `pytest` with `pytest-django`, against Postgres with PostGIS loaded with the small synthetic data (Phase 2 synthetic profile) | about 30 to 60 s |
| **Every spec ID tested** (Q-085) | Requirements with no test | `scripts/check_spec_ids.py` reads every requirement ID from `docs/spec/spec.md` (159 today) and fails if one is not named in a `@pytest.mark.spec("EFF-01")` marker. An ID that a gate checks instead (for example UI-05, checked by the Haiku review) is listed with its gate and a reason in `tests/spec_id_gates.toml` (Phase 4 creates it, so it can grow in Phase 5 without a change request). | under 1 s |
| **Coverage** (Q-085) | Code no test runs | `pytest-cov`, line and branch, `fail_under = 85`, migrations excluded | included above |
| **Queries per page** | Pages that run one query per row (N+1) | In every page test, `django_assert_max_num_queries(10)`. A page that needs more states its number in the test. | included above |
| **Browser smoke tests** (Q-086) | Pages that break in a real browser: JavaScript errors, a blank map, a modal that will not open | Playwright with Chromium (software WebGL), one test per page as an Admin on the small synthetic data, at 1440 px and 390 px wide. Each test checks that the page loads, the console has no errors, and the main element is visible (map canvas, table or form). | about 1 to 2 min |

### Haiku Review (Before Done Only)

Brandon's choice (Q-096): a quick second opinion from a fresh Claude on every turn that changed site code.

- **How:** the before-done hook runs, after every other check passes, `claude -p --model claude-haiku-5-5` with the turn's diff, `docs/quality/style-guide.md` and these instructions: follow the style guide; flag logic that is more complicated than it needs to be; flag slop (needless abstraction, code the spec did not ask for, vague names, half-finished work, JavaScript where htmx is simpler or htmx forced where a little JavaScript is simpler (Q-099)). It answers `OK` or a numbered list of problems, each with file, line and the rule.
- **Blocks:** any listed problem blocks the agent from finishing until it is fixed. If the agent disagrees with a point twice in a row, it reports the point to Brandon instead of looping.
- **Time and cost:** about 30 to 60 s and some usage, on turns that changed site code only.
- **Not on GitHub:** it needs a Claude login, which CI does not have.
- **Phase 4:** if Claude Code's built-in prompt or agent hook types fit, Phase 4 may use one instead of `claude -p`. The behaviour stays the same.

## Windows and Docker

Phase 4 puts every tool in `pyproject.toml` and the `uv` lock file. The hooks call one entry point, `scripts/gate.py`, with `--file <path>` (after each save), `--done` (before done) or `--staged` (at commit). It runs each tool:
- **Natively on Windows:** with `uv run`, against the native Postgres 18 service with PostGIS (installed in Phase 4).
- **In Docker:** inside the web container with `docker compose run --rm web`, against the Compose PostGIS database, when `UNIFIED_GATES=docker` is set. GitHub runs this way.

| Gate | Windows, native | Docker and GitHub |
|---|---|---|
| ruff, djLint, mypy, project scripts | `uv run`, pure Python | same, in the web image |
| Django checks, pytest, coverage | `uv run`, native Postgres with PostGIS | in the web container, Compose PostGIS |
| Playwright | `uv run playwright install chromium` once, then the tests | the same install in the web image |
| Haiku review | `claude` on Brandon's machine, where the agent runs | not run |

The hook scripts are Python, so they behave the same from Git Bash and PowerShell.

## Every Candidate, Chosen or Rejected

| Candidate (phase doc) | Decision |
|---|---|
| ruff lint and format, with complexity limits | Chosen, rules and limits above |
| Line limit per file (500), and per function | Chosen: 500 lines per file; per function, ruff's 50-statement and complexity limits |
| djLint | Chosen |
| `manage.py check`, `makemigrations --check` | Chosen |
| A migration linter | Rejected: Django's migrations cover only its own tables. The gold tables come from `schema.sql`, and roles use a model with no table (decision 006). |
| pytest-django with a coverage floor; every spec ID tested | Chosen, 85% (Q-085) |
| import-linter | Rejected: not chosen (Q-089). The 500-line limit, the 3-uses rules and the Haiku review keep apps apart. |
| Type checking | Chosen: mypy, moderate (Q-084) |
| vulture (dead code) | Rejected as a tool: the 3-uses rule already fails any function nothing calls (Q-090) |
| bandit | Rejected as a tool: ruff's S rules are the same checks |
| pip-audit | Rejected (Q-100) |
| No broad `except`, no `print` | Chosen: ruff BLE and T20 |
| No commented-out code, no TODO without an issue | Chosen, stricter: one comment per file, so neither can exist (Q-090) |
| No new JavaScript or front-end dependency without approval | Rejected as a hook (Q-096). JavaScript is used where it is simpler than htmx (Q-099), and the Haiku review checks that choice. |
| No em dashes in UI text | Chosen: no em dash in any file |
| Playwright end-to-end tests | Chosen as smoke tests, one per page (Q-086). Full user flows rejected as slow and brittle. |
| Visual comparison with `docs/ui/` screenshots | Rejected: there are no reference screenshots (Q-061) |
| Query performance on full-size data | Query counts per page chosen. A timed weekly run on full-size data rejected (Q-092). |
| Check settings locked to Brandon; code changes need test changes; new packages need approval | Proposed by the agent and not chosen (Q-096) |
| Session-start reminder of the rules | Rejected (Q-100) |
