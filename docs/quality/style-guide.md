# Style Guide

How the Unified DB Django code is written, decided with Brandon in Phase 3. Each rule is checked by a gate in [quality-gates.md](quality-gates.md) or by the Haiku review, which reads this file. Rules nobody can check are left out.

## Layout

**Five apps, one per sidebar group** (Q-097). Each has its own `urls.py` with `app_name`, included from the project `urls.py`.

| App | Pages |
|---|---|
| `core` | Sign In and Sign Out, Settings, Feedback, the page layout and sidebar, the one track map component (TRACK-01), Global Search, the gold models, and the versioned write functions |
| `survey` | Explore, Efforts, Effort, Sightings, Sighting, Edit and Delete |
| `photoid` | Individuals, Individual |
| `analysis` | Export, SQL (the sidebar's Data group; named `analysis` because `data` clashes with the `Data/` folder on Windows, CR-002) |
| `manage` | Track File Manager, Audit Log, Server |

Users and roles live in Django's admin and the `core` permissions (decision 006).

Inside an app:
```
survey/
  urls.py
  views.py          (split into views_efforts.py, views_sightings.py ... before it reaches 500 lines)
  forms.py
  templates/survey/
  static/survey/
  tests/
```

An app may import from `core`. Apps never import from each other: anything two apps share moves to `core`.

## Views

- **Plain functions, everywhere** (Q-101). No class-based views. One function per page or per action, named `<thing>_<action>`: `sighting_detail`, `effort_edit`, `track_import`.
- **Every view names its permission** with `@permission_required("core.<permission>", raise_exception=True)` (decision 006). Sign-in pages are the only exception.
- **Query code stays in the view** that uses it. Once the same query is needed in 3 places, it becomes one function in the app's `queries.py` (Q-090). A function written for one or two callers fails the 3-uses gate.
- **No service layer.** Writes to versioned records go through the functions in `core/versions.py` (edit, delete with dependents, restore; decision 004), because every app that edits uses them.

Example:
```python
@permission_required("core.browse", raise_exception=True)
def sighting_detail(request, legacy_id):
    sighting = get_object_or_404(SightingCurrent, legacy_id=legacy_id)
    samples = SampleCurrent.objects.filter(sighting_id=sighting.id)
    return render(request, "survey/sighting_detail.html", {"sighting": sighting, "samples": samples})
```

## Models

- **Gold tables are unmanaged** (`managed = False`). Pages read the `<table>_current` views (`SightingCurrent` and so on). Version history reads the base table.
- **Only `core/versions.py` writes** to versioned tables, each action in one `transaction.atomic()` block, with who, why and one `change_id` (decision 004).
- Django's own migrations cover only Django's tables and the permissions model.

## Templates and htmx

- **Names:** a page is `<app>/<page>.html`. A partial, a piece htmx swaps in, starts with an underscore: `survey/_sighting_rows.html`.
- **One URL per page.** When htmx asks (`request.htmx`, from `django-htmx`), the same view returns the partial instead of the page. Filters, paging and sorting work this way.
- **Swaps** target an element whose `id` matches the partial's name (`id="sighting-rows"` for `_sighting_rows.html`).
- **Modals** use htmx and the native `<dialog>` element (MODAL-01).
- **No inline `style=` attributes and no `onclick=`.** Styles go in the app's CSS, and behaviour in htmx attributes or the page's JavaScript file.

## JavaScript

- **Use JavaScript where it is genuinely cleaner and simpler than htmx, and don't force htmx where a little JavaScript is simpler** (Q-099). Maps (MapLibre GL JS and deck.gl, MAP-01) are JavaScript.
- One file per page that needs one: `static/<app>/<page>.js`, loaded only on that page. Plain modern JavaScript, no build step.
- The libraries the spec names are allowed (Q-006).

## Comments and Names

- **One comment per file, at the top,** saying what the file is for. No other comments anywhere (Q-090). Docstrings on functions and classes are allowed (Q-093). If code needs a comment to be understood, rename or simplify it instead.
- **Names say what the thing does or holds:** `track_points_by_year`, not `process_data` or `helper`. Python names are `snake_case`, classes `PascalCase`, and URL names match view names.

## Settings, Logging and Errors

- **One settings file**, `config/settings.py`, reading every secret and per-machine value from environment variables with `django-environ`. No per-environment settings files.
- **Logging:** each module uses `log = logging.getLogger(__name__)`. No `print`. An error is logged once, where it is handled.
- **Errors:** catch only a specific exception, and only where the page can do something useful with it (a form error, a message). Everything else reaches Django's error pages (ERR requirements). No `except Exception`.
- **Form input** is validated by Django forms, and errors show against their field (EDIT-05).

## Tests

- **pytest** with `pytest-django`. Tests live in `<app>/tests/test_<page>.py`, and browser smoke tests in `tests/browser/`.
- **Every test names the spec IDs it proves:** `@pytest.mark.spec("SDET-03")`. A test proves the requirement's Check column, not that the code runs.
- **Data:** the small synthetic data set (Phase 2 profile), loaded once per test run. Tests that need a particular record use pytest fixtures built on the synthetic generator, not hand-written rows.
- **Every page test** asserts its query count (`django_assert_max_num_queries`, 10 unless the test states another number).
- Repeated test setup becomes a fixture; the repeat gate counts tests too.

## Size

- At most 500 lines per file, 50 statements and 6 arguments per function, complexity 10 (quality-gates.md).
- Split a file by what its parts are about (`views_efforts.py`, `views_sightings.py`), never into `utils.py` or `helpers.py`.
