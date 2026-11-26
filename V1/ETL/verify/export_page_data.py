"""
Export what a build did, for the Data Pipeline page (Django/datahealth): every
value it changed, and every orphan, so the page shows exactly what the
pipeline does rather than a list kept by hand.

    python verify/export_page_data.py --db test_today

writes verify/reports/pipeline_fixes.json and verify/reports/pipeline_unlinked.json,
which ops/pipeline-page-data.sh copies next to Django/datahealth/pipeline.py. Reads
the swapped-in build (dbo and build).
"""

import argparse
import json
import pathlib

import psycopg

OUT = pathlib.Path(__file__).parent / "reports"

# (child table, its DB167 ID, Foreign Key, parent, parent's DB167 ID, the child's reference by DB167 ID)
LINKS = [
    ("DailyConditionT", "DailyConditionID", "daily_effort_id", "effort", "DailyEffortID"),
    ("DailyEventT", "DailyEventID", "daily_effort_id", "effort", "DailyEffortID"),
    ("SightingT", "SightingID", "daily_effort_id", "effort", "DailyEffortID"),
    ("SightingEventT", "SightingEventID", "sighting_id", "sighting", None),
    ("OtherSpeciesT", "OtherSpeciesID", "sighting_id", "sighting", None),
    ("SampleT", "SampleID", "sighting_id", "sighting", "SightingID"),
    ("IdentificationT", "IdentificationID", "sighting_id", "sighting", "SightingID"),
    ("TagSummaryT", "TagSummaryID", "sighting_id", "sighting", None),
]

# Foreign Keys copied from DB167 as they are, each checked against its parent:
# (table, its DB167 ID, Foreign Key, parent, date column).
COPIED = [
    ("IdentificationT", "IdentificationID", "IndividualID", "IndividualT", "Date"),
    ("SampleT", "SampleID", "IndividualID", "IndividualT", "Date"),
    ("TrackT", "TrackID", "ResearchGroupID", "ResearchGroupT", "SurveyDate"),
    ("TrackT", "TrackID", "TrackCompleteCodeID", "TrackCompleteCodeT", "SurveyDate"),
    ("TrackT", "TrackID", "SourceID", "SourceT", "SurveyDate"),
]

# Foreign Keys the website can set, by table: (its Primary Key, its DB167 ID, date column, Foreign Keys).
EDITABLE = {
    "DailyConditionT": ("id", "DailyConditionID", "Date", ["daily_effort_id"]),
    "DailyEventT": ("id", "DailyEventID", "Date", ["daily_effort_id"]),
    "SightingT": ("id", "SightingID", "Date", ["daily_effort_id", "species_id"]),
    "SightingEventT": ("id", "SightingEventID", "Date", ["daily_effort_id", "sighting_id"]),
    "OtherSpeciesT": ("id", "OtherSpeciesID", "Date", ["daily_effort_id", "sighting_id"]),
    "SampleT": ("id", "SampleID", "Date", ["daily_effort_id", "sighting_id", "sighting_event_id", "IndividualID"]),
    "IdentificationT": ("id", "IdentificationID", "Date", ["daily_effort_id", "sighting_id", "IndividualID"]),
    "TagSummaryT": ("TagSummaryID", "TagSummaryID", "Date", ["daily_effort_id", "sighting_id"]),
    "TrackT": ("TrackID", "TrackID", "SurveyDate",
               ["daily_effort_id", "ResearchGroupID", "TrackCompleteCodeID", "SourceID"]),
}


def ranges(ids):
    """1, 2, 3, 7 -> '1 to 3, 7'."""
    ids = sorted(ids)
    out, start = [], None
    for i, n in enumerate(ids):
        if start is None:
            start = n
        if i + 1 == len(ids) or ids[i + 1] != n + 1:
            out.append(str(start) if start == n else f"{start} to {n}")
            start = None
    return ", ".join(out)


def fixes(cur):
    cur.execute("""select table_name, column_name, kind, from_value, to_value, records
                   from build.value_changes order by table_name, column_name, records desc, from_value""")
    rows = []
    for table, column, kind, frm, to, n in cur.fetchall():
        if kind == "empty":
            frm, to = "(empty text)", None
        elif kind == "trim":
            frm, to = "(spaces at the start or end)", "(the same text without them)"
        rows.append({"table": table, "column": column, "from": frm, "to": to, "records": n, "kind": kind})
    return {"rows": rows}


def orphans(cur):
    out = {}
    for table, legacy, fk, parent, ref in LINKS:
        parent_table = "DailyEffortT" if parent == "effort" else "SightingT"
        combination = ("Research Group, Vessel and Date" if parent == "effort"
                       else "Research Group, Vessel, Date and Sighting")
        natural = "__effort" if parent == "effort" else "__sighting"
        key = "id" if table != "TagSummaryT" else "TagSummaryID"
        keyed = (f'build."keyed_{table}" k on k."{legacy}" = c."{legacy}"' if table != "TagSummaryT" else None)
        cur.execute(f"""
            with c as (select * from dbo."{table}" where {fk} is null and "Research Group" is not null),
            shared as (select __natural, count(*) as n from build."keyed_{parent_table}" where not __is_copy
                       group by 1)
            select c."{legacy}", c."Research Group", extract(year from c."Date")::int,
                   {f'c."{ref}"' if ref else 'null'} as ref,
                   {f'(c."{ref}" is not null and not exists (select 1 from raw."{parent_table}" p where p."{ref}" = c."{ref}"))' if ref else 'false'} as gone,
                   coalesce(s.n, 0) as candidates
            from c
            {'join ' + keyed if keyed else ''}
            left join shared s on s.__natural = {'k.' + natural if keyed else
                ('build.key_hash(array[build.key_text(c."Research Group"), build.key_text(c."Vessel"), '
                 'to_char(c."Date"::date, \'YYYY-MM-DD\'), build.key_text(c."Sighting")])')}
        """)
        groups = {}
        for lid, group, year, refid, gone, candidates in cur.fetchall():
            if candidates > 1:
                reason = f"More than one {parent} with its {combination}, and nothing tells them apart"
            elif gone:
                reason = f"Its {parent} ({refid}) was deleted from DB167"
            else:
                reason = f"No {parent} with its {combination}"
            groups.setdefault((reason, group, year), []).append(lid)
        rows = [{"reason": r, "group": g, "year": y, "records": len(ids), "ids": ranges(ids)}
                for (r, g, y), ids in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0][1], kv[0][2] or 0))]
        if rows:
            out[table] = rows
    # Tracks that name a removed Effort are not exported: the Data Pipeline page reads them from
    # the database each time it loads (pipeline.unmatched_tracks).
    # A Foreign Key DB167 has, naming a record its parent table lacks.
    for table, legacy, fk, parent, date in COPIED:
        cur.execute(f"""
            select d."{legacy}", d."Research Group", extract(year from d."{date}")::int, r."{fk}"
            from dbo."{table}" d join raw."{table}" r on r."{legacy}" = d."{legacy}"
            where d."{fk}" is null and r."{fk}" is not null""")
        add(out, table, cur.fetchall(), lambda value: f"Its {fk} ({value}) is not in DB167's {parent}")
    # A Foreign Key a website edit set, naming a record that is not there.
    for table, (key, legacy, date, fks) in EDITABLE.items():
        for fk in fks:
            cur.execute(f"""
                select d."{legacy}", d."Research Group", extract(year from d."{date}")::int, e.changes ->> %s
                from build.edits e join dbo."{table}" d on d."{key}"::text = e.target_pk
                where e.target_table = %s and e.changes ->> %s is not null and d."{fk}" is null""",
                        [fk, table, fk])
            add(out, table, cur.fetchall(),
                lambda value: f"A website edit set its {fk} to {value}, a record that is not there")
    return out


def add(out, table, found, reason):
    """Add a table's orphans (DB167 ID, Research Group, year, value), grouped by reason, group and year."""
    groups = {}
    for lid, group, year, value in found:
        groups.setdefault((reason(value), group, year), []).append(lid)
    for (r, g, y), ids in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0][1] or "", kv[0][2] or 0)):
        out.setdefault(table, []).append({"reason": r, "group": g, "year": y, "records": len(ids), "ids": ranges(ids)})


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default="test_today")
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    with psycopg.connect(f"postgresql://cascadia:cascadia@db:5432/{args.db}") as conn, conn.cursor() as cur:
        f, o = fixes(cur), orphans(cur)
    (OUT / "pipeline_fixes.json").write_text(json.dumps(f, ensure_ascii=False) + "\n")
    (OUT / "pipeline_unlinked.json").write_text(json.dumps(o, ensure_ascii=False, indent=1) + "\n")
    print(f"{len(f['rows'])} value changes; orphans: "
          + ", ".join(f"{t} {sum(r['records'] for r in rows):,}" for t, rows in o.items()))


if __name__ == "__main__":
    main()
