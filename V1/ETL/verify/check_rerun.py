"""
Prove that the pipeline, run again on a newer copy of DB167, finds every
record it had before and applies every edit from the audit log to the right
one.

The first build (--before, already swapped in: dbo and build) is from the copy
of DB167 the website's edits were made against; the second (--after, in
dbo_next and build_next) is from today's copy, with the same audit log. Then:

  1. Every edit in the audit log is on its record in the second build, with
     its value. An edit whose record the build did not find fails, unless the
     record's Legacy ID (kept in app.audit_log.legacy_pk) is gone from DB167.
  2. Records in the 8 tables with a hashed Primary Key are matched between the
     builds by that key. A record DB167 renumbered must keep its id; a record
     whose id changed must have had one of its key columns changed in DB167.
  3. Every Foreign Key to an effort or a sighting points at the same record in
     both builds, unless DB167 changed the record or its parent.
  4. Every value that differs between the two builds, on the same record,
     differs because DB167's value changed, or because the spelling rule chose
     another spelling now that DB167 has new values (worked out again for each
     copy of DB167 by spelling.py, not read from the build).

    python verify/check_rerun.py [--before test_last] [--after test_today]
"""

import argparse
import collections
import json
import sys

import csv
import pathlib

import psycopg

import spelling
from compare_with_live import HASHED, KEYED, Report, canon, canon_geom, canon_json, rows, rows_kv

# Efforts DB167 removed as copies, and the Effort each track of one is moved to.
REMOVED_EFFORTS = {int(r["removed_effort"]): int(r["kept_effort"])
                   for r in csv.DictReader(open(pathlib.Path(__file__).parent.parent / "dbt/seeds/removed_efforts.csv"))}

URL = "postgresql://cascadia:cascadia@db:5432/{}"


def by(rows_, key):
    return {r[key]: r for r in rows_}


def check_edits(before, after, report):
    """1. Every edit lands on its record in the second build."""
    edits = rows(after, "select target_table, target_pk, changes from build_next.edits")
    deleted = rows(after, "select target_table, target_pk from build_next.edit_rows where state = 'deleted'")
    created = rows(after, "select target_table, target_pk from build_next.edit_rows where state = 'created'")
    for e in edits:
        table, pk, changes = e["target_table"], e["target_pk"], e["changes"]
        if table not in KEYED:
            report.explain(table, "(edit)", "the table stays in raw (rule 1); the edit has nothing to apply to", pk)
            continue
        key = "id" if table in HASHED else KEYED[table]
        record = rows(after, f'select * from dbo_next."{table}" where "{key}"::text = %s', [pk])
        if not record:
            missing_record(before, after, report, table, pk)
            continue
        record = record[0]
        for column, value in changes.items():
            if column not in record:
                continue
            want = canon_json(value, canon(record[column]))
            got = canon_geom(record[column])
            if column == "geom":
                continue  # a track's line: from app.track_geometry, checked below
            if got == want:
                report.explain(table, "(edit)", "applied", {"pk": pk, "column": column})
            elif column in ("vessel_id", "track_status", "point_count", "length_nm", "file_name"):
                report.explain(table, "(edit)", f"{column} is worked out again, not taken from the edit",
                               {"pk": pk, "edit": want, "now": got})
            elif column == "daily_effort_id" and got is None:
                report.explain(table, "(edit)", "its effort is no longer in DB167; the track waits to be matched",
                               {"pk": pk})
            else:
                report.fail(table, "(edit)", "not applied", {"pk": pk, "column": column, "edit": want, "now": got})
    for d in deleted:
        if d["target_table"] not in KEYED:
            continue
        key = "id" if d["target_table"] in HASHED else KEYED[d["target_table"]]
        if rows(after, f'select 1 from dbo_next."{d["target_table"]}" where "{key}"::text = %s', [d["target_pk"]]):
            report.fail(d["target_table"], "(delete)", "deleted on the website, but back", d["target_pk"])
        else:
            report.explain(d["target_table"], "(delete)", "stays deleted", d["target_pk"])
    for c in created:
        key = "id" if c["target_table"] in HASHED else KEYED[c["target_table"]]
        if rows(after, f'select 1 from dbo_next."{c["target_table"]}" where "{key}"::text = %s', [c["target_pk"]]):
            report.explain(c["target_table"], "(create)", "created on the website, and there", c["target_pk"])
        else:
            report.fail(c["target_table"], "(create)", "created on the website, but missing", c["target_pk"])


def missing_record(before, after, report, table, pk):
    """An edit whose record the second build does not have. Fine only when DB167
    no longer has the record: its Legacy ID, as the audit log keeps it (or as
    the first build had it), is gone from raw."""
    legacy = {r["legacy_pk"] for r in rows(after, """
        select l.legacy_pk from build_next.audit_entries e join app.audit_log l on l.id = e.id
        where e.target_table = %s and e.target_pk = %s and l.legacy_pk is not null""", [table, pk])}
    key = "id" if table in HASHED else KEYED[table]
    legacy |= {str(r["legacy"]) for r in rows(
        before, f'select "{KEYED[table]}" as legacy from dbo."{table}" where "{key}"::text = %s', [pk])}
    if not legacy:
        report.fail(table, "(edit)", "its record is missing, and no Legacy ID says which DB167 record it was",
                    {"pk": pk})
        return
    still = [lid for lid in legacy if rows(after, f'select 1 from raw."{table}" where "{KEYED[table]}"::text = %s',
                                           [lid])]
    if still:
        report.fail(table, "(edit)", "its record is missing, though DB167 still has its Legacy ID",
                    {"pk": pk, "Legacy ID": still})
    else:
        report.explain(table, "(edit)", "its record is no longer in DB167, so the edit waits unused",
                       {"pk": pk, "Legacy ID": sorted(legacy)})


def key_values(cur, schema, table, legacy, ids):
    """The key columns' values of some records, from their keyed build table."""
    if not ids:
        return {}
    return by(rows(cur, f'select * from {schema}."keyed_{table}" where "{legacy}" = any(%s)', [list(ids)]), legacy)


KEY_COLUMNS = {
    "DailyEffortT": ["Research Group", "Vessel", "Date"],
    "DailyEventT": ["Research Group", "Vessel", "Date", "EventDateTime", "Code"],
    "DailyConditionT": ["Research Group", "Vessel", "Date", "ConditionDateTime"],
    "SightingT": ["Research Group", "Vessel", "Date", "Sighting"],
    "SightingEventT": ["Research Group", "Vessel", "Date", "Sighting", "EventTime", "SightEvent", "Field ID",
                       "EventID", "Reaction", "SightEventComments", "Dec Lat", "Dec Long"],
    "OtherSpeciesT": ["Research Group", "Vessel", "Date", "Sighting", "Species", "Count", "Comments"],
    "SampleT": ["Research Group", "Vessel", "Date", "Sighting", "Sample #", "Sample Number", "Field ID", "Event",
                "Sample Type", "SampleTime", "Reaction", "Comments"],
    "IdentificationT": ["Research Group", "Vessel", "Date", "Sighting", "IndividualID", "Field ID"],
}


def check_matching(before, after, report, summary):
    """2. Records matched by their hashed Primary Key."""
    for table, legacy in HASHED.items():
        a = {r["id"]: r[legacy] for r in rows(before, f'select id, "{legacy}" from dbo."{table}"')}
        b = {r["id"]: r[legacy] for r in rows(after, f'select id, "{legacy}" from dbo_next."{table}"')}
        a_by_legacy = {v: k for k, v in a.items()}
        b_by_legacy = {v: k for k, v in b.items()}
        same = sum(1 for i in a.keys() & b.keys() if a[i] == b[i])
        renumbered = [(a[i], b[i]) for i in a.keys() & b.keys() if a[i] != b[i]]
        gone = [i for i in a.keys() - b.keys()]
        new = [i for i in b.keys() - a.keys()]
        changed_key, removed = [], []
        old_rows = key_values(before, "build", table, legacy, [a[i] for i in gone])
        new_rows = key_values(after, "build_next", table, legacy, [a[i] for i in gone if a[i] in b_by_legacy])
        for i in gone:
            lid = a[i]
            if lid in b_by_legacy:
                o, n = old_rows.get(lid, {}), new_rows.get(lid, {})
                diff = [c for c in KEY_COLUMNS[table] if canon(o.get(c)) != canon(n.get(c))]
                shared = (o.get("__shared", 1) or 1) > 1 or (n.get("__shared", 1) or 1) > 1
                if diff:
                    changed_key.append(lid)
                    report.explain(table, "(id)", "DB167 changed a key column, so the record has a new id: "
                                   + ", ".join(sorted(diff)), {"DB167 ID": lid, "before": {c: canon(o.get(c)) for c in diff},
                                                               "after": {c: canon(n.get(c)) for c in diff}})
                elif shared:
                    changed_key.append(lid)
                    report.explain(table, "(id)", "its combination is shared with another record in one copy and "
                                   "not the other, so the Legacy ID is in its id in one copy only", lid)
                else:
                    report.fail(table, "(id)", "a new id with the same key columns", lid)
            else:
                removed.append(lid)
        came = [b[i] for i in new if b[i] not in a_by_legacy]
        # A record removed and one added under the same parent (the same
        # sighting, or for an effort's own records the same effort) are most
        # likely one record DB167 re-imported with different values.
        parent = "__sighting" if "Sighting" in KEY_COLUMNS[table] and table != "SightingT" else "__effort"
        if table == "DailyEffortT":
            parent = "__natural"
        old_full = key_values(before, "build", table, legacy, removed)
        new_full = key_values(after, "build_next", table, legacy, came)
        by_parent = collections.defaultdict(list)
        for lid, r in new_full.items():
            by_parent[r.get(parent)].append(lid)
        paired = set()
        for lid in removed:
            o = old_full.get(lid, {})
            match = [n for n in by_parent.get(o.get(parent), []) if n not in paired]
            if match and o.get(parent) is not None:
                n = match[0]
                paired.add(n)
                diff = sorted(c for c in KEY_COLUMNS[table] if canon(o.get(c)) != canon(new_full[n].get(c)))
                report.explain(table, "(record)", "re-imported by DB167 with changed values, so a new id",
                               {"before": lid, "after": n,
                                "changed": {c: [canon(o.get(c)), canon(new_full[n].get(c))] for c in diff}})
            else:
                report.explain(table, "(record)", "removed from DB167", lid)
        for lid in came:
            if lid not in paired:
                report.explain(table, "(record)", "added to DB167", lid)
        for old, nid in renumbered:
            report.explain(table, "(id)", "DB167 renumbered it; matched by its hashed key", {"before": old, "after": nid})
        summary[table] = {"before": len(a), "after": len(b), "same id and DB167 ID": same,
                          "renumbered by DB167, same id": len(renumbered),
                          "key columns changed in DB167, new id": len(changed_key),
                          "re-imported with changed values, new id": len(paired),
                          "removed from DB167": len(removed) - len(paired), "added to DB167": len(came) - len(paired)}


CHILD_LINKS = {
    "DailyConditionT": ["daily_effort_id"], "DailyEventT": ["daily_effort_id"],
    "SightingT": ["daily_effort_id"], "SightingEventT": ["daily_effort_id", "sighting_id"],
    "OtherSpeciesT": ["daily_effort_id", "sighting_id"], "IdentificationT": ["daily_effort_id", "sighting_id"],
    "SampleT": ["daily_effort_id", "sighting_id", "sighting_event_id"], "TagSummaryT": ["daily_effort_id", "sighting_id"],
    "TrackT": ["daily_effort_id"],
}
PARENT = {"daily_effort_id": "DailyEffortT", "sighting_id": "SightingT", "sighting_event_id": "SightingEventT"}


def check_links(before, after, report):
    """3. Foreign Keys keep pointing at the same records."""
    parent_ids = {}
    for p in PARENT.values():
        parent_ids[p] = ({r[0] for r in rows_kv(before, f'select id from dbo."{p}"')},
                         {r[0] for r in rows_kv(after, f'select id from dbo_next."{p}"')})
    for table, links in CHILD_LINKS.items():
        key = "id" if table in HASHED else KEYED[table]
        cols = ", ".join(links)
        a = {r[0]: r[1:] for r in rows_kv(before, f'select "{key}", {cols} from dbo."{table}"')}
        b = {r[0]: r[1:] for r in rows_kv(after, f'select "{key}", {cols} from dbo_next."{table}"')}
        for k in a.keys() & b.keys():
            for i, col in enumerate(links):
                x, y = a[k][i], b[k][i]
                if x == y:
                    continue
                p = PARENT[col]
                if x is not None and x not in parent_ids[p][1]:
                    report.explain(table, col, f"its {p} record is gone or has a new id in today's DB167",
                                   {"record": k})
                elif y is not None and y not in parent_ids[p][0]:
                    report.explain(table, col, f"its {p} record is new in today's DB167", {"record": k})
                elif x is None or y is None:
                    report.explain(table, col, "DB167 changed the record's key columns or its parent's",
                                   {"record": k, "before": x, "after": y})
                else:
                    report.fail(table, col, "points at another existing record", {"record": k, "before": x, "after": y})


def check_values(before, after, report):
    """4. A value that changed on a record changed in DB167, or by the spelling rule."""
    merges_before = {k: to for k, (to, _) in spelling.merges(before).items()}
    merges_after = {k: to for k, (to, _) in spelling.merges(after).items()}
    raw_columns = {}
    for r in rows(after, "select table_name, column_name from information_schema.columns where table_schema = 'raw'"):
        raw_columns.setdefault(r["table_name"], set()).add(r["column_name"])
    for table, legacy in KEYED.items():
        key = "id" if table in HASHED else legacy
        a = by(rows(before, f'select * from dbo."{table}"'), key)
        b = by(rows(after, f'select * from dbo_next."{table}"'), key)
        ra = by(rows(before, f'select * from raw."{table}"'), legacy)
        rb = by(rows(after, f'select * from raw."{table}"'), legacy)
        for k in a.keys() & b.keys():
            A, B = a[k], b[k]
            for col in B:
                if col not in A:
                    continue  # a column DB167 has gained since
                x, y = canon_geom(A[col]), canon_geom(B[col])
                if x == y:
                    continue
                if col in raw_columns.get(table, ()):
                    ox, oy = ra.get(A.get(legacy), {}).get(col), rb.get(B.get(legacy), {}).get(col)
                    if canon(ox) != canon(oy):
                        report.explain(table, col, "DB167's value changed", {"record": k, "before": x, "after": y})
                    elif merges_before.get((table, col, ox)) != merges_after.get((table, col, oy)):
                        report.explain(table, col, "the spelling rule chose another spelling, as DB167 has new "
                                                   "values", {"record": k, "raw": ox, "before": x, "after": y})
                    elif A.get(legacy) != B.get(legacy):
                        report.explain(table, col, "a renumbered record: DB167's ID column", {"record": k})
                    elif table == "TrackT" and col == "EffortID" and ox in REMOVED_EFFORTS \
                            and y == REMOVED_EFFORTS[ox]:
                        report.explain(table, col, "the removed-effort rule (seeds/removed_efforts.csv) moves a "
                                                   "track from an Effort DB167 removed as a copy to the one it "
                                                   "kept", {"record": k, "raw": canon(ox), "after": y})
                    else:
                        report.fail(table, col, "changed, though DB167's value did not",
                                    {"record": k, "raw": canon(ox), "before": x, "after": y})
                else:
                    report.explain(table, col, "worked out again from changed inputs",
                                   {"record": k, "before": x, "after": y})


def check_plan_tracks(after, report):
    """The plan's four tracks."""
    want = {1588: 29152, 1592: 29178, 1266: 10016, 1336: None}
    for track, effort in want.items():
        got = rows(after, 'select e."DailyEffortID" from dbo_next."TrackT" t left join dbo_next."DailyEffortT" e '
                          'on e.id = t.daily_effort_id where t."TrackID" = %s', [track])
        got = got[0]["DailyEffortID"] if got else "missing"
        if got == effort:
            report.explain("TrackT", "daily_effort_id", "the plan's track matches hold", {"track": track, "effort": got})
        else:
            report.fail("TrackT", "daily_effort_id", "a plan track match is wrong",
                        {"track": track, "want": effort, "got": got})


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--before", default="test_last")
    parser.add_argument("--after", default="test_today")
    parser.add_argument("--report")
    args = parser.parse_args()
    report, summary = Report(), {}
    with psycopg.connect(URL.format(args.before)) as b, psycopg.connect(URL.format(args.after)) as a:
        before, after = b.cursor(), a.cursor()
        check_edits(before, after, report)
        check_matching(before, after, report, summary)
        check_links(before, after, report)
        check_values(before, after, report)
        check_plan_tracks(after, report)

    print("Records matched by their hashed Primary Key:")
    for table, s in summary.items():
        print(f"  {table}: " + "; ".join(f"{k} {v:,}" for k, v in s.items()))
    print(f"\nExplained: {sum(report.counts.values()):,}")
    for (table, column, reason), n in sorted(report.counts.items()):
        print(f"  {n:>8,}  {table}.{column}: {reason}")
        if n <= 3 or "plan" in reason or "renumbered" in reason or "re-imported" in reason:
            for e in report.examples[(table, column, reason)][:3]:
                print(f"            {e}")
    print(f"\nUnexplained: {sum(report.unexplained.values()):,}")
    for (table, column, reason), n in sorted(report.unexplained.items()):
        print(f"  {n:>8,}  {table}.{column}: {reason}")
        for e in report.unexplained_examples[(table, column, reason)]:
            print(f"            {e}")
    if args.report:
        with open(args.report, "w") as f:
            json.dump({"matching": summary,
                       "explained": [{"table": t, "column": c, "reason": r, "count": n,
                                      "examples": report.examples[(t, c, r)]} for (t, c, r), n in
                                     sorted(report.counts.items())],
                       "unexplained": [{"table": t, "column": c, "reason": r, "count": n,
                                        "examples": report.unexplained_examples[(t, c, r)]}
                                       for (t, c, r), n in sorted(report.unexplained.items())]},
                      f, indent=1, default=str)
    return 1 if report.unexplained else 0


if __name__ == "__main__":
    sys.exit(main())
