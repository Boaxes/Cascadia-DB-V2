# Definition of Done

What each Phase 5 feature (a page or a piece of a page) must pass before the agent calls it done. Phase 5 runs as one step (Q-059), so this list is checked per feature as the build goes, and again for the whole site at the end.

## Checklist

1. **Every spec ID for the feature has a test** that proves its Check column, marked `@pytest.mark.spec("...")`. An ID checked by a gate instead is listed in `tests/spec_id_gates.toml` with the reason.
2. **The before-done hook is green:** fast checks, the 3-uses and repeat rules, types, Django checks, tests with 85% coverage, every spec ID tested, query counts, and the browser smoke tests ([quality-gates.md](quality-gates.md)).
3. **The Haiku review found nothing,** or the agent reported the points it disagreed with to Brandon.
4. **The agent checked the page in the browser preview** at 1440 px and 390 px wide, with the console clear of errors, and compared it with its mockup in `mockups/`. Close in layout and content is the bar, not pixel-exact (Q-061).
5. **Nothing the spec did not ask for:** no extra pages, buttons, settings, dashboards or options.
6. **No frozen document changed** without a change request Brandon accepted (CLAUDE.md, The Gate).
7. **GitHub's run is green** for the pushed branch.
8. **STATUS.md says what was finished,** what is next, and anything waiting on Brandon.
