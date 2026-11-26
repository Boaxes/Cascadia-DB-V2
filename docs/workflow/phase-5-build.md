# Phase 5: Build

**Goal:** build the website the spec describes, page by page, so that each page matches its approved screenshot and passes every gate.

**Writes:** the repository, except frozen Phase 1 to 3 outputs and protected files.
**Branches:** one per feature (`phase-5-<feature>`), each with a pull request.

## Order

Agree the build order with Brandon at the start of the phase. Record it in STATUS.md, and build in that order. A sensible default:

1. Sidebar and layout
2. Sightings
3. Efforts
4. Tracks and their settings
5. Photo-ID catalogs
6. Audit log
7. Analysis
8. Exports
9. Admin

## For Each Feature

1. Re-read its spec section, its requirement IDs and its screenshots in `docs/ui/`.
2. Write the tests first, from the acceptance criteria, citing the requirement IDs.
3. Build it the way the style guide says. If something in the spec cannot be built as written, or needs a choice the spec did not make, stop. Add a change request and ask. Do not improvise, and do not add anything the spec does not ask for.
4. Run every gate. Check the page in the built-in browser preview against its screenshots, at desktop and mobile sizes, with the browser console clear of errors.
5. Go through the definition of done in `docs/quality/definition-of-done.md`.
6. Commit and push the feature branch, and open a pull request with a screenshot of the finished page next to the approved one. Brandon previews it locally and merges.

## Exit Checklist

- [ ] Every page in the spec is built, and every requirement ID is covered by a passing test.
- [ ] Every change request is resolved.
- [ ] Brandon has previewed the whole site locally.
- [ ] STATUS.md updated, and Brandon asked to approve.
