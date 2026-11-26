# Phase 1: Spec And Mockup

**Goal:** turn [V2Spec.MD](../../V2Spec.MD) into a spec with nothing left to interpret, and agree on how every page looks before any of it is built.

**Writes:** `docs/spec/`, `mockups/`, `docs/ui/`, plus the workflow logs and `scratch/`.
**Branch:** `phase-1-spec`.

## Steps

### 1. Inventory V1

Read V1's URLs, views and templates (`V1/Django`). Write `docs/spec/v1-inventory.md`: one row per page or feature with what it does today, who uses it, and a proposal (keep, change, merge or drop) with a reason. V1's routes are Sightings, Efforts, Tracks (by effort, by file), Explore, Export, Audit, Manage, the JSON APIs and login. Confirm the proposals with Brandon before relying on them.

### 2. Ask

Work through every item in V2Spec.MD and every row of the inventory, asking in rounds (see "Asking Questions" in CLAUDE.md). Expect at least these topics. Each one needs a decision, not a default:

- **Users, groups and permissions:** V1's groups and permissions are a mess (read V1's `admintools`, settings and any group or permission checks, and list what exists today). Propose a smaller model with a handful of named roles, where each can see and edit, and how a user is given a role. Ask whether anything is public. The answer must fit in one short table.
- **Navigation:** the sidebar groups and their order, what sits at the top, and what the landing page shows.
- **Each page:** what it is for, what data it shows, filters and their defaults, sorting, paging, actions, and empty and error states.
- **Map:** which WebGL library to use (for example MapLibre GL JS, deck.gl, or both). Lay out the options with their costs, and ask which views need a map.
- **Tracks:** the single track view, which settings a user controls (points, lines, gaps, dashes, timeline events, colour by), and where those settings live.
- **Analysis:** what "basic analysis outside the browser" means in practice (for example read-only SQL through DuckDB WASM over the DuckLake tables, Parquet or CSV downloads, saved queries, a notebook starter). Ask which of these are in scope.
- **Audit log:** what a user sees. The storage design waits for Phase 2.
- **Photo-ID catalogs:** how MnID, Bm and ErId appear on the site.
- **Extra features:** V2Spec.MD invites proposals. Propose each one separately, with its value and cost. Only the ones Brandon says yes to go into the spec.

### 3. Write The Spec

Write `docs/spec/spec.md` with these sections:

1. Purpose, Goals and Non-Goals.
2. Users and Permissions.
3. Information Architecture: the sidebar tree and URL map. Each Django app owns its own URLs.
4. Pages: one subsection per page, giving purpose, data shown, filters with defaults, actions, permissions, empty and error states, and **acceptance criteria**.
5. Cross-Cutting Behaviour: track display settings, map behaviour, exports, analysis, audit log (user-facing), and search.
6. Out Of Scope.
7. Assumptions: an empty list by the end of the phase.

Every requirement gets a stable ID (`NAV-01`, `SIGHT-03`, `TRACK-07`) and is written so a test can check it: "The Sightings list defaults to the current calendar year", not "sensible defaults". Phase 5 tests cite these IDs.

### 4. Mock It Up

- Write static HTML in `mockups/`: one file per page, one shared `mockups/style.css`, and no build step. Use plain HTML and CSS. Use a little inline JS only to fake interactions that htmx will do for real (opening a panel, switching a tab).
- Use a Databricks-style left sidebar with grouped sections. Follow the writing rules in CLAUDE.md: Title Case, no possessive labels, no em dashes.
- Use realistic but invented values (species, vessels, dates, coordinates in the Salish Sea and the Pacific coast). Do not paste real records.
- Draw maps as a static picture or a plain placeholder box. The map library is decided in the spec, not proven here.
- Preview with the built-in browser: `preview_start` with the `mockups` configuration in `.claude/launch.json`. Check each page yourself before showing Brandon.
- Iterate with Brandon. Keep the spec and the mockups in step: a change to one is a change to both.

### 5. Capture The Reference Screenshots

Once Brandon is happy with the mockups, capture every page at 1440×900 and 390×844 into `docs/ui/<page>-desktop.png` and `docs/ui/<page>-mobile.png`. With the mockup server running:

```
"/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" --headless=new --disable-gpu --hide-scrollbars --window-size=1440,900 --screenshot="docs/ui/sightings-desktop.png" http://localhost:8080/sightings.html
```

Write `docs/ui/README.md` to list each screenshot with its page and spec section. Phase 5 builds against these.

## Exit Checklist

- [ ] `docs/spec/v1-inventory.md`, with every proposal confirmed.
- [ ] `docs/spec/spec.md`: every requirement has an ID and acceptance criteria, there is no "TBD" and no open assumption, and the extra features are listed only if Brandon said yes.
- [ ] A mockup for every page in the spec, previewed and agreed.
- [ ] Screenshots in `docs/ui/` with the index.
- [ ] Every question answered and logged in `questions-log.md`.
- [ ] STATUS.md updated, the branch pushed, and Brandon asked to approve.
