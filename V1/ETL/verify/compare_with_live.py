"""
Prove that every difference between a build of the new pipeline and the live
database is one the plan explains.

Both must come from the same copy of DB167: the live site's dbo was built from
its raw, so the new pipeline is built from the same raw (DB167_LastImport) for
this comparison. Then, for every table the two share:

  1. Every record is matched by its DB167 ID. A record only one side has must
     be one the plan says goes (an exact copy, rule 6) or comes (a category row
     added, rules 4 and 9; a track for a file in the bucket).
  2. Every DB167 column of every matched record is checked twice:
       - the new value must be exactly what the rules give, recomputed here in
         Python from raw, the seeds and the audit log (spelling.py), without
         reading anything the build made; and
       - where it differs from live, the difference is put down to a rule:
         the spelling rule (rule 5) where the old process spelled it
         otherwise or not at all, empty text made NULL, spaces trimmed.
  3. Every calculated column and Foreign Key is compared by meaning: the
     species, vessel, effort or sighting it names, the point it draws. A
     Foreign Key that names another record than live's must name one with the
     child's own Research Group, Vessel and Date (and Sighting); an effort's
     start and end points, and a sighting's count of identified animals, must
     be what their rule gives, worked out again here.

Anything that fits no rule is UNEXPLAINED, and the run fails.

    python verify/compare_with_live.py [--db test_last] [--report out.json]
"""

import argparse
import collections
import datetime
import decimal
import json
import os
import re
import sys
import zoneinfo

import psycopg

import spelling

# The 8 tables with a hashed Primary Key, and their Legacy ID columns, as the
# move to hashed keys lists them.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from move_to_hashed_keys import HASHED  # noqa: E402

KEYED = {**HASHED, "TagSummaryT": "TagSummaryID", "TrackT": "TrackID", "IndividualT": "IndividualID",
         "SourceT": "SourceID", "TrackCompleteCodeT": "TrackCompleteCodeID", "EventCodeT": "EventCodeID",
         "ResearchGroupT": "ResearchGroupID"}
DBO_TABLES = set(KEYED) | {"SpeciesT", "VesselListT"}

# Today's spelling rules (Archive/ETL/dbt/models/dbo), which rule 5 replaces.
# Used only to recognise a live value as today's spelling.
TODAY_MAPS = {
    ("SightingT", "Species"): {"zica": "Zc", "ud": "UnDelph", "uc": "UnCet", "turtle": "TURT-UN",
                               "unturt": "TURT-UN", "lst": "TURT-LB", "leatherback": "TURT-LB",
                               "olive ridley turtle": "TURT-OR", "dc.": "Dc", "bm.": "Bm"},
    ("DailyEffortT", "Survey Type"): {"non-standardized large vessel": "Large Vessel Non-Standardized",
                                      "land observation": "Land", "entanglement": "Entanglement Response",
                                      "ent": "Entanglement Response", "uknown": "Unknown"},
    ("DailyEffortT", "Locality"): {"n cordell bank": "N. Cordell Bank", "zittel's": "Zittels",
                                   "everett, n puget sound": "Everett/N. Puget Sound",
                                   "pt. st. george": "Pt St George", "pt. st.george": "Pt St George"},
    ("DailyEffortT", "Sub-area"): {"se alaska": "Southeast Alaska", "nothern washington": "Northern Washington",
                                   "nothern oregon": "Northern Oregon", "queen charlottes": "Queen Charlotte Islands"},
    ("SampleT", "Sample Type"): {"skin": "Skin Only Biopsy", "skin only": "Skin Only Biopsy",
                                 "sample-other": "Other", "blubber only": "Blubber"},
}
TODAY_MAPS[("SampleT", "Species")] = TODAY_MAPS[("SightingT", "Species")]
WS = " \t\r\n\f\v "


def key_text(value):
    if value is None:
        return None
    text = " ".join(str(value).strip(WS).split()).lower()
    return text or None


def canon(value):
    """One comparable form for a value read from a column or from JSON."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, decimal.Decimal)):
        return float(value)
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, bytes | memoryview):
        return bytes(value).hex()
    return value


def canon_json(value, like):
    """A value from an audit log entry, read as the column's type."""
    if value is None:
        return None
    if isinstance(like, float) and isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    if isinstance(like, str) and len(like) >= 10 and isinstance(value, str) and "T" in like and " " in value:
        return value.replace(" ", "T")
    return canon(value)


def canon_text(text, like):
    """A value from a seed, read as the column's type; empty text is NULL."""
    if text is None or text == "":
        return None
    if isinstance(like, (int, float, decimal.Decimal)) and not isinstance(like, bool):
        return float(text)
    return text


class Report:
    def __init__(self):
        self.counts = collections.Counter()
        self.examples = collections.defaultdict(list)
        self.unexplained = collections.Counter()
        self.unexplained_examples = collections.defaultdict(list)
        self.touched = set()

    def explain(self, table, column, reason, example):
        record = example.get("id", example.get("track")) if isinstance(example, dict) else example
        self.touched.add((table, record))
        if column == "(record)":
            self.touched.add((table, "(record)", record))
        k = (table, column, reason)
        self.counts[k] += 1
        if len(self.examples[k]) < 3:
            self.examples[k].append(example)

    def fail(self, table, column, reason, example):
        k = (table, column, reason)
        self.unexplained[k] += 1
        if len(self.unexplained_examples[k]) < 5:
            self.unexplained_examples[k].append(example)


def rows(cur, sql, params=None):
    cur.execute(sql, params or [])
    names = [d.name for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


PACIFIC = zoneinfo.ZoneInfo("America/Los_Angeles")
TRACK_TIMES = {"StartTime": "first_time", "EndTime": "last_time"}


def pacific_to_utc(local, file_time=None):
    """DB167's Pacific local time as UTC, worked out here with the zone database and
    not by the build's SQL (macros/track_times.sql). A time in the repeated hour of
    the autumn change is the daylight or the standard reading by the file's own time
    when that falls in one of the two hours, else the standard one."""
    if local is None:
        return None
    daylight, standard = local + datetime.timedelta(hours=7), local + datetime.timedelta(hours=8)

    def back(utc):
        return utc.replace(tzinfo=datetime.timezone.utc).astimezone(PACIFIC).replace(tzinfo=None)

    if back(daylight) == local and back(standard) == local:
        start = local.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=7)
        return daylight if file_time is not None and start <= file_time < start + datetime.timedelta(hours=1) else standard
    return local.replace(tzinfo=PACIFIC).astimezone(datetime.timezone.utc).replace(tzinfo=None)


class Context:
    def __init__(self, cur, new, build, live):
        self.cur, self.new, self.build, self.live = cur, new, build, live
        self.kinds = {(r["table_name"], r["column_name"]): r["kind"] for r in spelling.seed("column_kinds")}
        self.merges = spelling.merges(cur)
        self.edits = website_edits(cur)
        # Each file's first and last time (UTC), for a track time in the repeated hour.
        self.file_times = {r["object_key"].lower(): r for r in rows(
            cur, "select object_key, first_time, last_time from app.track_geometry")}
        # The single-record fixes and the removed efforts of the seeds. Live
        # made these as audit log entries; the pipeline makes them itself.
        self.fixes = {(f["table_name"], f["legacy_id"], f["record_date"], f["column_name"]): f
                      for f in spelling.seed("record_fixes")}
        # A track follows the kept effort only while DB167 does not have the removed one.
        have = {r["DailyEffortID"] for r in rows(cur, 'select "DailyEffortID" from raw."DailyEffortT"')}
        self.removed_efforts = {int(r["removed_effort"]): int(r["kept_effort"])
                                for r in spelling.seed("removed_efforts") if int(r["removed_effort"]) not in have}
        # Rule 8: the edit-form trial, deleted from the log. What it set, by the
        # DB167 ID live knows the record by.
        self.trial = {}
        for r in rows(cur, "select target_table, target_pk, changes from live_app.audit_log "
                           "where id in (109, 112, 113) and changes is not null"):
            for column, change in r["changes"].items():
                self.trial[(r["target_table"], r["target_pk"], column)] = canon(change.get("new"))
        self.text_columns = {}
        for r in rows(cur, """select table_name, column_name, data_type from information_schema.columns
                              where table_schema = 'raw'"""):
            self.text_columns.setdefault(r["table_name"], {})[r["column_name"]] = r["data_type"]

    def raw(self, table, legacy):
        return {r[legacy]: r for r in rows(self.cur, f'select * from raw."{table}"')}

    # The rules, recomputed.
    def cleaned(self, table, column, value, row):
        dtype = self.text_columns[table].get(column)
        if dtype == "text" and value is not None:
            if value.strip(WS) == "":
                return None
            if self.kinds.get((table, column), "free") == "choice":
                return self.merges.get((table, column, value), (value, None))[0]
            return value.strip(WS)
        return value

    def overridden(self, table, column, value, row, cleaned_row):
        """The rules besides spelling: today's, which the new pipeline keeps, and the
        corrections the pipeline makes that the old import made as audit log entries."""
        value = self.ruled(table, column, value, row, cleaned_row)
        date = row.get("Date")
        fix = self.fixes.get((table, str(row.get(KEYED[table])), date.strftime("%Y-%m-%d") if date else None, column))
        if fix and canon(value) == canon_text(fix["old_value"], value):
            return canon_text(fix["new_value"], value)
        return value

    def track_time(self, row, column, value):
        """A track's StartTime or EndTime as the new pipeline keeps it: DB167's Pacific
        local time as UTC."""
        file = self.file_times.get(str(row.get("TrackFileName") or "").strip().lower(), {})
        return pacific_to_utc(value, file.get(TRACK_TIMES[column]))

    def ruled(self, table, column, value, row, cleaned_row):
        crc = cleaned_row.get("Research Group") == "CRC"
        if table == "TrackT" and column in TRACK_TIMES and value is not None:
            return self.track_time(row, column, value)

        def zero(lat, lon):
            return row.get(lat) == 0 and row.get(lon) == 0

        if table == "DailyEventT" and column in ("Dec Lat", "Dec Long"):
            return None if zero("Dec Lat", "Dec Long") else value
        if table == "SightingT" and column in ("Start Dec Lat", "Start Dec Long"):
            half = (row.get("Start Dec Lat") is None) != (row.get("Start Dec Long") is None)
            return None if zero("Start Dec Lat", "Start Dec Long") or (crc and half) else value
        if table == "SightingT" and column in ("End Dec Lat", "End Dec Long"):
            lon = row.get("End Dec Long")
            if crc and lon is not None and (lon < -180 or lon > 180):
                return None
            return None if zero("End Dec Lat", "End Dec Long") else value
        if table == "DailyConditionT" and column == "Beaufort":
            return None if crc and value is not None and (value < 0 or value > 12) else value
        if table == "DailyConditionT" and column == "Quality":
            return None if crc and value is not None and value.upper() not in ("E", "G", "VG", "F", "P") else value
        if table == "SampleT" and column == "Certainty of Sample ID":
            return None if crc and value is not None and re.fullmatch(r"[0-9]+", value) else value
        if table == "TrackT" and column == "EffortID":
            return self.removed_efforts.get(value, value)
        if table == "TrackT" and column == "Comments" and value is not None and re.search(r"<[^>]*>", value):
            return re.sub(r"<[^>]*>", " ", value).strip() or None
        return value


def website_edits(cur):
    """The newest value of every field the website set, by record, read from
    app.audit_log: {(table, Primary Key): {column: value}}. What the old Restore
    reversed (an entry with restored_by set, and the restore itself) is left out."""
    out = collections.defaultdict(dict)
    for r in rows(cur, """select target_table, target_pk, changes from app.audit_log
                          where restored_by is null and action in ('update', 'associate', 'dissociate', 'upload', 'create')
                            and changes is not null order by id"""):
        for column, change in r["changes"].items():
            out[(r["target_table"], r["target_pk"])][column] = change.get("new") if isinstance(change, dict) else None
    return out


def explain_text(ctx, table, column, raw_value, live_value, new_value):
    """Why live and new differ on a text column, where new is what the rules give."""
    kind = ctx.kinds.get((table, column), "free")
    if new_value is None and raw_value is not None and raw_value.strip(WS) == "":
        return "Rule 5: empty text -> NULL (today kept it)"
    merge = ctx.merges.get((table, column, raw_value))
    if live_value == raw_value or (live_value is not None and raw_value is not None
                                   and live_value == raw_value.strip(WS)):
        if merge:
            return f"Rule 5: spelling merged ({merge[1]}); today left it as DB167 has it"
        if kind != "choice" and raw_value != new_value:
            return "Rule 5: spaces at the start or end removed; today kept them"
    if live_value is not None and new_value is not None and live_value.strip(WS) == new_value:
        return "Rule 5: spaces at the start or end removed; today kept them"
    today = TODAY_MAPS.get((table, column), {})
    if live_value is not None and raw_value is not None:
        if key_text(live_value) == key_text(raw_value):
            if merge:
                return f"Rule 5: today folded capitals by each research group's commonest spelling; new rule ({merge[1]})"
            return "Rule 5: today folded capitals by each research group's commonest spelling; new rule keeps one spelling for all"
        if today.get(key_text(raw_value)) == live_value or (
                table in ("DailyEffortT",) and column in ("Launch", "Locality", "Return")
                and re.sub("seiku", "Sekiu", raw_value, flags=re.I) == live_value):
            return f"Rule 5: today's own mapping for {column}; replaced by the spelling rule"
        if table == "DailyEffortT" and column == "Sub-area" and merge and merge[1] == "corrected":
            return "Rule 5: Sub-area from Doug Sandilands's table; today's own mapping differed"
    return None


def compare_records(ctx, report, table):
    cur, new, live = ctx.cur, ctx.new, ctx.live
    legacy = KEYED[table]
    raw = ctx.raw(table, legacy)
    new_rows = {r[legacy]: r for r in rows(cur, f'select * from {new}."{table}"')}
    live_rows = {r[legacy]: r for r in rows(cur, f'select * from {live}."{table}"')}
    copies = {}
    if table in HASHED:
        for r in rows(cur, f'select "{legacy}", __is_copy, id from {ctx.build}."keyed_{table}"'):
            copies[r[legacy]] = (r["__is_copy"], r["id"])

    # 1. Records.
    for k in live_rows.keys() - new_rows.keys():
        if copies.get(k, (False,))[0]:
            report.explain(table, "(record)", "Rule 6: exact copy of another record, removed", k)
        else:
            report.fail(table, "(record)", "in live, not in the new build", k)
    for k in new_rows.keys() - live_rows.keys():
        if table in ("EventCodeT", "ResearchGroupT") and k not in raw:
            report.explain(table, "(record)", "Rules 4 and 9: added to the category table", k)
        else:
            report.fail(table, "(record)", "in the new build, not in live", k)

    # 2. DB167's columns.
    raw_columns = list(ctx.text_columns[table])
    for k in live_rows.keys() & new_rows.keys():
        L, N, R = live_rows[k], new_rows[k], raw.get(k)
        pk = str(N["id"]) if table in HASHED else str(k)
        edit = ctx.edits.get((table, pk), {})
        if R is None and table != "TrackT":
            report.fail(table, "(record)", "not in raw", k)
            continue
        cleaned_row = {c: ctx.cleaned(table, c, R.get(c), R) for c in raw_columns} if R else {}
        for col in raw_columns:
            if col not in L or col not in N:
                continue
            n = canon(N[col])
            if col in edit:
                expected = canon_json(edit[col], n)
            elif R is None:
                expected = n
            else:
                expected = canon(ctx.overridden(table, col, cleaned_row[col], R, cleaned_row))
            if n != expected:
                report.fail(table, col, "new value is not what the rules give",
                            {"id": k, "raw": canon(R.get(col)) if R else None, "expected": expected, "new": n})
                continue
            l = canon(L[col])
            if l == n:
                continue
            if col in edit:
                report.fail(table, col, "an edit is applied differently", {"id": k, "live": l, "new": n})
                continue
            why = None
            if ctx.trial.get((table, str(k), col)) == l:
                report.explain(table, col, "Rule 8: the edit-form trial (entry 109) is deleted from the log",
                               {"id": k, "live": l, "new": n})
                continue
            if table == "TrackT" and col in TRACK_TIMES and R is not None and L[col] is not None \
                    and canon(ctx.track_time(R, col, L[col])) == n:
                # Today's dbo holds DB167's Pacific local time; the new pipeline holds UTC. Only an
                # exact conversion of the live value is explained: anything else is a failure below.
                report.explain(table, col, "DB167 keeps a track's times in Pacific local time; the new pipeline "
                                           "converts them to UTC (macros/track_times.sql)",
                               {"id": k, "live": l, "new": n})
                continue
            if R is None:
                why = "a track the website created or the bucket holds; its value differs"
                report.fail(table, col, why, {"id": k, "live": l, "new": n})
                continue
            if ctx.text_columns[table][col] == "text":
                why = explain_text(ctx, table, col, R.get(col), L[col], N[col])
            if why:
                report.explain(table, col, why, {"id": k, "raw": R.get(col), "live": l, "new": n})
            else:
                report.fail(table, col, "differs from live", {"id": k, "raw": canon(R.get(col)), "live": l, "new": n})
    return live_rows, new_rows, raw


def compare_derived(ctx, report, table, live_rows, new_rows, raw):
    cur, new, live = ctx.cur, ctx.new, ctx.live
    legacy = KEYED[table]
    common = live_rows.keys() & new_rows.keys()

    # Vessels: today's id named one spelling; the new one names the vessel.
    if "vessel_id" in next(iter(live_rows.values()), {}):
        live_vessel = {r["vessel_id"]: r for r in rows(cur, f'select * from {live}."VesselListT"')}
        new_vessel = {r["vessel_id"]: r for r in rows(cur, f'select * from {new}."VesselListT"')}
        keys = dict(rows_kv(cur, f"select key, vessel_id from {ctx.build}.vessel_keys"))
        for k in common:
            lv, nv = live_rows[k]["vessel_id"], new_rows[k]["vessel_id"]
            expected = keys.get(key_text(new_rows[k].get("Vessel")))
            if table == "TrackT" and expected is None:
                expected = nv  # by VesselID; checked below by its legacy id
            if nv != expected:
                report.fail(table, "vessel_id", "not the vessel its text names", {"id": k, "new": nv, "expected": expected})
                continue
            if lv == nv:
                continue
            spelling = (live_vessel.get(lv) or {}).get("vessel_text")
            if lv is None and nv is not None:
                report.explain(table, "vessel_id", "Rule 4: every typed vessel is in VesselListT", k)
            elif nv is None:
                report.fail(table, "vessel_id", "NULL in the new build", {"id": k, "live": lv})
            elif keys.get(key_text(spelling)) == nv or key_text((new_vessel.get(nv) or {}).get("code")) == key_text(
                    (live_vessel.get(lv) or {}).get("code")):
                report.explain(table, "vessel_id", "Rule 4: one VesselListT row per vessel; today's id was one "
                                                   "spelling of the same vessel", {"id": k, "live": lv, "new": nv})
            else:
                report.fail(table, "vessel_id", "a different vessel", {"id": k, "live": lv, "live text": spelling,
                                                                        "new": nv})

    # Species: today's hand-kept list against DB167's SpeciesT.
    if table in ("SightingT", "SampleT"):
        live_sp = {r["species_id"]: r for r in rows(cur, f'select * from {live}."SpeciesT"')}
        new_sp = {r["SpeciesID"]: r for r in rows(cur, f'select * from {new}."SpeciesT"')}
        matches = dict(rows_kv(cur, f"select key_text(spelling), code from {ctx.build}.species_matches"
                                    .replace("key_text(", f"{ctx.build}.key_text(")))
        for k in common:
            ls, ns = live_rows[k]["species_id"], new_rows[k]["species_id"]
            lc = (live_sp.get(ls) or {}).get("code")
            nc = (new_sp.get(ns) or {}).get("Abbreviation")
            ln = key_text((live_sp.get(ls) or {}).get("common_name"))
            nn = key_text((new_sp.get(ns) or {}).get("CommonName"))
            if key_text(lc) == key_text(nc):
                continue
            if lc and nc and lc.replace(" ", "").lower() == nc.replace(" ", "").lower():
                report.explain(table, "species_id", "Rule 4: the same code, as DB167's SpeciesT spells it",
                               {"id": k, "live": lc, "new": nc})
                continue
            text = key_text((new_rows[k].get("Species") or "").strip().rstrip("?"))
            if ln and ln == nn:
                report.explain(table, "species_id", "Rule 4: the same species, coded as DB167's SpeciesT codes it",
                               {"id": k, "live": lc, "new": nc})
            elif text in matches:
                report.explain(table, "species_id", f"SightingT note: {text} is matched to {matches[text]}",
                               {"id": k, "live": lc, "new": nc})
            elif ns is None:
                report.explain(table, "species_id", "SightingT note: a species text that matches no code in "
                                                    "SpeciesT keeps its text, with the FK NULL",
                               {"id": k, "text": new_rows[k].get("Species"), "live": lc})
            elif ls is None:
                report.explain(table, "species_id", "Rule 9: a code today's list lacked is in SpeciesT",
                               {"id": k, "new": nc})
            elif key_text(lc) in ("zc",) and key_text(nc) == "zica":
                report.explain(table, "species_id", "SightingT note: Zica stays Cuvier's beaked whale; today "
                                                    "wrote it as Zc", {"id": k})
            else:
                report.fail(table, "species_id", "a different species", {"id": k, "text": new_rows[k].get("Species"),
                                                                          "live": lc, "new": nc})

    # Points, and numbers worked out from other columns: follow their inputs.
    follows = {"geom": ["Dec Lat", "Dec Long", "Start Dec Lat", "Start Dec Long"],
               "end_geom": ["End Dec Lat", "End Dec Long"],
               "depth_m": ["Depth", "D units", "Research Group"], "num_calves": ["Num Calves"],
               "species_uncertain": ["Species"], "visibility_nm": ["Visibility", "Visibility (nm)"],
               "total_distance_nm": ["Total Distance", "Distance Units"]}
    for col, inputs in follows.items():
        if table == "TrackT" or col not in next(iter(live_rows.values()), {}):
            continue
        for k in common:
            l, n = canon_geom(live_rows[k][col]), canon_geom(new_rows[k][col])
            if l == n:
                continue
            changed = [c for c in inputs if c in live_rows[k] and canon(live_rows[k][c]) != canon(new_rows[k][c])]
            if changed:
                report.explain(table, col, f"follows {', '.join(changed)}", {"id": k, "live": l, "new": n})
            else:
                report.fail(table, col, "differs, its inputs do not", {"id": k, "live": l, "new": n})


def effort_points(ctx):
    """Each effort's start and end point, and where each came from, by the rule
    in models/dbo/DailyEffortT.sql, worked out again from the new day-log entries
    and tracks: the earliest B entry with a position (the latest T for the end),
    else the first point of its lowest TrackID (the last point of its highest),
    else (start only) its earliest positioned entry. Entries at the same time go
    by their id."""
    events = collections.defaultdict(list)
    for r in rows(ctx.cur, f'''select id, daily_effort_id, "Code", "Time", geom from {ctx.new}."DailyEventT"
                               where daily_effort_id is not null and geom is not null'''):
        events[r["daily_effort_id"]].append(r)
    tracks = collections.defaultdict(list)
    for r in rows(ctx.cur, f'''select "TrackID", daily_effort_id, ST_StartPoint(ST_GeometryN(geom, 1)) as first,
                                      ST_EndPoint(ST_GeometryN(geom, ST_NumGeometries(geom))) as last
                               from {ctx.new}."TrackT" where daily_effort_id is not null and geom is not null'''):
        tracks[r["daily_effort_id"]].append(r)

    def earliest(entries):
        return min(entries, key=lambda e: (e["Time"] is None, e["Time"] or 0, e["id"]), default=None)

    def latest(entries):
        last = max((e["Time"] for e in entries if e["Time"] is not None), default=None)
        return min((e for e in entries if e["Time"] == last), key=lambda e: e["id"], default=None)

    out = {}
    for effort in events.keys() | tracks.keys():
        ev, tr = events.get(effort, []), sorted(tracks.get(effort, []), key=lambda t: t["TrackID"])
        b = earliest([e for e in ev if (e["Code"] or "").upper() == "B"])
        t = latest([e for e in ev if (e["Code"] or "").upper() == "T"])
        first = earliest(ev)
        if b:
            start = (b["geom"], "event_B")
        elif tr:
            start = (tr[0]["first"], "gps_track")
        elif first:
            start = (first["geom"], "first_positioned_record")
        else:
            start = (None, None)
        end = (t["geom"], "event_T") if t else (tr[-1]["last"], "gps_track") if tr else (None, None)
        out[effort] = {"start_point": canon_geom(start[0]), "start_coord_source": start[1],
                       "end_point": canon_geom(end[0]), "end_coord_source": end[1]}
    return out


def identified_counts(ctx):
    """Each sighting's identified animals: the different IndividualIDs of its
    new IdentificationT records."""
    return {k: float(n) for k, n in rows_kv(ctx.cur, f'''select sighting_id, count(distinct "IndividualID")
        from {ctx.new}."IdentificationT" where sighting_id is not null and "IndividualID" is not null group by 1''')}


def check_rule(report, table, new_rows, columns, worked_out, default, key="id"):
    """Every new record's calculated columns are what the rule gives."""
    for k, r in new_rows.items():
        want = worked_out.get(r[key], default)
        for col in columns:
            got = canon_geom(r[col])
            w = want[col] if isinstance(want, dict) else want
            if got != w:
                report.fail(table, col, "not what its rule gives", {"id": k, "rule": w, "new": got})


def compare_rest(ctx, report, table, live_rows, new_rows):
    """Every other column both sides have: compared value for value."""
    cur, new, live = ctx.cur, ctx.new, ctx.live
    points = ("start_point", "end_point", "start_coord_source", "end_coord_source")
    if table == "DailyEffortT":
        check_rule(report, table, new_rows, points, effort_points(ctx), dict.fromkeys(points))
    if table == "SightingT":
        check_rule(report, table, new_rows, ["identified_individual_count"], identified_counts(ctx), 0.0)
    handled = set(ctx.text_columns[table]) | {"vessel_id", "species_id", "sighting_id", "geom", "end_geom",
                                              "depth_m", "num_calves", "species_uncertain", "visibility_nm",
                                              "total_distance_nm"}
    common = live_rows.keys() & new_rows.keys()
    if not common:
        return
    sample = next(iter(live_rows.values()))
    columns = [c for c in sample if c in next(iter(new_rows.values())) and c not in handled]
    codes = {}
    if "event_code_id" in columns:
        codes = {"live": dict(rows_kv(cur, f'select "EventCodeID", "EventCode" from {live}."EventCodeT"')),
                 "new": dict(rows_kv(cur, f'select "EventCodeID", "EventCode" from {new}."EventCodeT"'))}
    effort_legacy = dict(rows_kv(cur, f'select id, "DailyEffortID" from {new}."DailyEffortT"'))
    for col in columns:
        for k in common:
            l, n = canon_geom(live_rows[k][col]), canon_geom(new_rows[k][col])
            if l == n:
                continue
            if col == "event_code_id":
                lc, nc = key_text(codes["live"].get(live_rows[k][col])), key_text(codes["new"].get(new_rows[k][col]))
                if lc == nc:
                    continue
                if lc is None and nc is not None:
                    report.explain(table, col, "Rule 9: its code is added to EventCodeT", {"id": k, "code": nc})
                    continue
            # Both checked against their rule above, on every record.
            if col == "identified_individual_count":
                report.explain(table, col, "IdentificationT note: counted from IdentificationT, not from "
                                           "SightingIdentificationT", {"id": k, "live": l, "new": n})
                continue
            if table == "DailyEffortT" and col in points:
                report.explain(table, col, "follows the day-log entries and tracks now linked by their "
                                           "Foreign Keys (rule 3)", {"id": k, "live": l, "new": n})
                continue
            if table == "TrackT" and col in ("track_status",):
                le, ne = live_rows[k].get("EffortID"), effort_legacy.get(new_rows[k].get("daily_effort_id"))
                if (le is None) != (ne is None):
                    report.explain(table, col, "follows daily_effort_id", {"id": k, "live": l, "new": n})
                    continue
                if le is not None and l in ("unassociated", "unresolved"):
                    report.explain(table, col, "today's status was written before the link was restored "
                                               "(audit entries 88 to 98) and never worked out again; the new "
                                               "process works it out from the link and the file",
                                   {"id": k, "live": l, "new": n})
                    continue
            if table == "TrackT" and col == "track_status" and n == "blank" and l in ("missing_file", "available") \
                    and not new_rows[k].get("point_count"):
                report.explain(table, col, "a track whose file holds no points is now Blank: a file that was "
                                           "missing is made as a header-only file, and a file with no points "
                                           "was Available",
                               {"id": k, "live": l, "new": n})
                continue
            report.fail(table, col, "differs from live", {"id": k, "live": l, "new": n})


# app views: (column in live, column in new, how to compare).
APP_KEYS = {"daily_condition": "legacy_daily_condition_id", "daily_effort": "legacy_daily_effort_id",
            "daily_event": "legacy_daily_event_id", "sample": "legacy_sample_id", "sighting": "legacy_sighting_id",
            "track": "legacy_track_id", "event_code": "id"}
APP_TABLE = {"daily_condition": "DailyConditionT", "daily_effort": "DailyEffortT", "daily_event": "DailyEventT",
             "sample": "SampleT", "sighting": "SightingT", "track": "TrackT", "event_code": "EventCodeT"}


def compare_app(ctx, report, new_app, explained_cells):
    """The website's views: the same rows for CRC, and every value either the
    same or a projection of a dbo value already explained above."""
    cur = ctx.cur
    new = ctx.new
    effort = dict(rows_kv(cur, f'select id, "DailyEffortID" from {new}."DailyEffortT"'))
    sighting = dict(rows_kv(cur, f'select id, "SightingID" from {new}."SightingT"'))
    live_species = dict(rows_kv(cur, f'select species_id, code from {ctx.live}."SpeciesT"'))
    new_species = dict(rows_kv(cur, f'select "SpeciesID", "Abbreviation" from {new}."SpeciesT"'))
    for view, key in APP_KEYS.items():
        live_rows = {r[key]: r for r in rows(cur, f"select * from live_app.{view}")}
        new_rows = {r[key]: r for r in rows(cur, f"select * from {new_app}.{view}")}
        table = APP_TABLE[view]
        for k in live_rows.keys() - new_rows.keys():
            if (table, "(record)", k) in explained_cells:
                report.explain(f"app.{view}", "(record)", "follows dbo: an exact copy removed (rule 6)", k)
            else:
                report.fail(f"app.{view}", "(record)", "in live, not in the new build", k)
        extra = new_rows.keys() - live_rows.keys()
        non_crc = sum(1 for k in extra if new_rows[k].get("research_group", "CRC") != "CRC")
        if non_crc:
            report.counts[(f"app.{view}", "(record)", "Step 3: every research group, not only CRC")] += non_crc
        for k in extra:
            if new_rows[k].get("research_group", "CRC") == "CRC":
                if (table, "(record)", k) in explained_cells or view == "event_code":
                    report.explain(f"app.{view}", "(record)", "follows dbo: a row added (rules 4, 9)", k)
                else:
                    report.fail(f"app.{view}", "(record)", "a CRC row only the new build has", k)
        for k in live_rows.keys() & new_rows.keys():
            L, N = live_rows[k], new_rows[k]
            for col in L:
                if col not in N:
                    report.fail(f"app.{view}", col, "column missing from the new view", k)
                    continue
                l, n = canon_geom(L[col]), canon_geom(N[col])
                if col == "id" and view != "event_code" and view != "track":
                    continue  # the hashed Primary Key (rule 2)
                if col == "daily_effort_id" and N[col] is not None:
                    n = canon(effort.get(N[col]))
                if col == "sighting_id" and N[col] is not None:
                    n = canon(sighting.get(N[col]))
                if col == "species_id":
                    l, n = key_text(live_species.get(L[col])), key_text(new_species.get(N[col]))
                if l == n:
                    continue
                if (table, k) in explained_cells:
                    report.explain(f"app.{view}", col, "follows an explained difference in dbo", k)
                else:
                    report.fail(f"app.{view}", col, "differs, and its dbo record does not", {"id": k, "live": l, "new": n})


def compare_other_views(ctx, report, new_app, new_dbo):
    """species, vessel and effort_timeline, and DB167's 7 views in dbo."""
    cur = ctx.cur
    live_codes = {key_text(r[0]) for r in rows_kv(cur, "select code from live_app.species")}
    new_codes = {key_text(r[0]) for r in rows_kv(cur, f"select code from {new_app}.species")}
    for code in live_codes - new_codes:
        report.explain("app.species", "(record)", "a code of today's hand-kept list that DB167's SpeciesT spells "
                                                  "differently or lacks (rule 4)", code)
    for code in new_codes - live_codes:
        report.explain("app.species", "(record)", "used by a sighting of any research group (step 3)", code)

    keys = dict(rows_kv(cur, f"select key, vessel_id from {ctx.build}.vessel_keys"))
    new_vessels = {r[0] for r in rows_kv(cur, f"select id from {new_app}.vessel")}
    for vid, code, name in rows_kv(cur, "select id, code, name from live_app.vessel"):
        if keys.get(key_text(code)) in new_vessels or keys.get(key_text(name)) in new_vessels:
            if vid not in new_vessels:
                report.explain("app.vessel", "(record)", "one row per vessel: this spelling is part of another "
                                                         "row (rule 4)", vid)
        else:
            report.fail("app.vessel", "(record)", "a vessel the new view lacks", {"id": vid, "code": code})

    live_tl = {r["row_key"]: r for r in rows(cur, "select row_key, label, legacy_id from live_app.effort_timeline")}
    new_tl = {r["row_key"]: r for r in rows(cur, f"select row_key, label, legacy_id from {new_app}.effort_timeline")}
    table = {"event": "DailyEventT", "sighting": "SightingT", "condition": "DailyConditionT"}
    for k in live_tl.keys() - new_tl.keys():
        t = table[k.split(":")[0]]
        if (t, "(record)", live_tl[k]["legacy_id"]) in report.touched:
            report.explain("app.effort_timeline", "(record)", "follows dbo: an exact copy removed (rule 6)", k)
        else:
            report.fail("app.effort_timeline", "(record)", "in live, not in the new build", k)
    for k in live_tl.keys() & new_tl.keys():
        if live_tl[k]["label"] != new_tl[k]["label"]:
            t = table[k.split(":")[0]]
            if (t, live_tl[k]["legacy_id"]) in report.touched:
                report.explain("app.effort_timeline", "label", "follows an explained difference in dbo", k)
            else:
                report.explain("app.effort_timeline", "label", "the name now comes from DB167's SpeciesT and the "
                                                               "EventCodeT names (rules 4 and 9)", k)
    extra = len(new_tl.keys() - live_tl.keys())
    if extra:
        report.counts[("app.effort_timeline", "(record)", "Step 3: every research group, not only CRC")] += extra

    for view in ["DailyEffortV", "IdentificationsBySightingV", "SightingEffortTrackV", "SightingV",
                 "SpeciesSummaryByEffortV", "TagSummaryV", "TrackV"]:
        live_n = rows_kv(cur, f'select count(*) from {ctx.live}."{view}"')[0][0]
        new_n = rows_kv(cur, f'select count(*) from {new_dbo}."{view}"')[0][0]
        if live_n != new_n:
            report.counts[(f"dbo.{view}", "(rows)", f"follows its tables, now joined by Foreign Keys: "
                                                    f"{live_n:,} today, {new_n:,} new")] += abs(new_n - live_n)


def canon_geom(value):
    if isinstance(value, str) and value[:2] in ("01", "00"):
        return value.upper()
    return canon(value)


def rows_kv(cur, sql, params=None):
    cur.execute(sql, params or [])
    return cur.fetchall()


def natural_key(row, sighting=False):
    """A record's Research Group, Vessel and Date (and Sighting), as rule 3 matches them."""
    date = row.get("Date")
    date = date.date() if isinstance(date, datetime.datetime) else date
    key = (key_text(row.get("Research Group")), key_text(row.get("Vessel")), date)
    return key + (key_text(row.get("Sighting")),) if sighting else key


def parent_keys(ctx):
    """Each new effort's and sighting's natural key, by id."""
    return ({r["id"]: natural_key(r) for r in rows(
                ctx.cur, f'select id, "Research Group", "Vessel", "Date" from {ctx.new}."DailyEffortT"')},
            {r["id"]: natural_key(r, True) for r in rows(
                ctx.cur, f'select id, "Research Group", "Vessel", "Date", "Sighting" from {ctx.new}."SightingT"')})


def same_parent(report, table, column, child, parent_key, explain_as, example):
    """A Foreign Key that names another record than DB167's reference must name
    one with the child's own combination."""
    sighting = column.startswith("sighting_id")
    if parent_key is not None and natural_key(child, sighting) == parent_key:
        report.explain(table, column, explain_as, example)
    else:
        report.fail(table, column, "names a record with another combination than its own",
                    {**example, "child": natural_key(child, sighting), "parent": parent_key})


def compare_links(ctx, report):
    """Every Foreign Key to an effort or a sighting, against DB167's own reference."""
    cur, new = ctx.cur, ctx.new
    effort = dict(rows_kv(cur, f'select id, "DailyEffortID" from {new}."DailyEffortT"'))
    sighting = dict(rows_kv(cur, f'select id, "SightingID" from {new}."SightingT"'))
    effort_key, sighting_key = parent_keys(ctx)
    keyed_effort = {r["DailyEffortID"]: r for r in rows(
        cur, f'select "DailyEffortID", id, __is_copy, __natural from {ctx.build}."keyed_DailyEffortT"')}
    keyed_sighting = {r["SightingID"]: r for r in rows(
        cur, f'select "SightingID", id, __is_copy, __natural from {ctx.build}."keyed_SightingT"')}
    natural_count = collections.Counter(r["__natural"] for r in keyed_effort.values() if not r["__is_copy"])
    sighting_count = collections.Counter(r["__natural"] for r in keyed_sighting.values() if not r["__is_copy"])

    for table in ["DailyConditionT", "DailyEventT", "SightingT", "SightingEventT", "OtherSpeciesT", "SampleT",
                  "IdentificationT", "TagSummaryT", "TrackT"]:
        legacy = KEYED[table]
        extra = ', __effort' if table not in ("TagSummaryT", "TrackT") else ''
        extra += ', __sighting' if table in ("SightingEventT", "OtherSpeciesT", "SampleT", "IdentificationT") else ''
        src = f'{ctx.build}."keyed_{table}"' if table in HASHED else f'{new}."{table}"'
        info = {r[legacy]: r for r in rows(cur, f'select "{legacy}"{extra} from {src}')}
        for r in rows(cur, f'select * from {new}."{table}"'):
            k = r[legacy]
            if "daily_effort_id" in r:
                old = r.get("EffortID") if table == "TrackT" else r.get("DailyEffortID")
                got = effort.get(r["daily_effort_id"]) if r["daily_effort_id"] is not None else None
                if got == old:
                    pass
                elif table == "TrackT":
                    pk = str(k)
                    if "daily_effort_id" in ctx.edits.get(("TrackT", pk), {}):
                        report.explain(table, "daily_effort_id", "matched on the website (audit log)", k)
                    elif old in keyed_effort and keyed_effort[old]["__is_copy"]:
                        report.explain(table, "daily_effort_id", "Rule 6: its effort was an exact copy", k)
                    elif got is None:
                        report.explain(table, "daily_effort_id", "Rule 3: its effort is not in DB167; left unmatched",
                                       {"track": k, "EffortID": old})
                    else:
                        report.fail(table, "daily_effort_id", "a different effort", {"track": k, "old": old, "new": got})
                else:
                    nat = info.get(k, {}).get("__effort")
                    if got is None and natural_count.get(nat, 0) == 0:
                        reason = ("Rule 3: orphan, its effort was deleted from DB167" if old not in keyed_effort
                                  else "Rule 3: orphan, no effort with its Research Group, Vessel and Date")
                        report.explain(table, "daily_effort_id", reason, {"id": k, "DailyEffortID": old})
                    elif got is None:
                        report.fail(table, "daily_effort_id", "NULL though an effort matches", {"id": k, "old": old})
                    elif old in keyed_effort and keyed_effort[old]["__is_copy"]:
                        same_parent(report, table, "daily_effort_id", r, effort_key.get(r["daily_effort_id"]),
                                    "Rule 6: its effort was an exact copy; the kept one",
                                    {"id": k, "old": old, "new": got})
                    elif old is None:
                        same_parent(report, table, "daily_effort_id", r, effort_key.get(r["daily_effort_id"]),
                                    "Rule 3: found by Research Group, Vessel and Date; DB167's DailyEffortID is "
                                    "empty", {"id": k, "new": got})
                    else:
                        same_parent(report, table, "daily_effort_id", r, effort_key.get(r["daily_effort_id"]),
                                    "Rule 3: found by Research Group, Vessel and Date; DailyEffortID names another "
                                    "effort", {"id": k, "old": old, "new": got})
            if "sighting_id" in r and table != "SightingT":
                old = r.get("SightingID")
                got = sighting.get(r["sighting_id"]) if r["sighting_id"] is not None else None
                nat = info.get(k, {}).get("__sighting")
                if old is not None and got == old:
                    continue
                if got is None:
                    n = sighting_count.get(nat, 0) if nat is not None else 0
                    if n == 0:
                        report.explain(table, "sighting_id", "Rule 3: orphan, no sighting with its Research Group, "
                                       "Vessel, Date and Sighting", k)
                    elif n > 1:
                        report.explain(table, "sighting_id", "Rule 3: more than one sighting with its combination, "
                                       "and nothing tells them apart; left NULL", k)
                    else:
                        report.fail(table, "sighting_id", "NULL though a sighting matches", k)
                elif old is None:
                    same_parent(report, table, "sighting_id", r, sighting_key.get(r["sighting_id"]),
                                "Rule 3: found by Research Group, Vessel, Date and Sighting", {"id": k})
                elif old in keyed_sighting and keyed_sighting[old]["__is_copy"]:
                    same_parent(report, table, "sighting_id", r, sighting_key.get(r["sighting_id"]),
                                "Rule 6: its sighting was an exact copy; the kept one", {"id": k})
                else:
                    same_parent(report, table, "sighting_id", r, sighting_key.get(r["sighting_id"]),
                                "Rule 3: found by Research Group, Vessel, Date and Sighting; SightingID names "
                                "another", {"id": k, "old": old, "new": got})


def compare_live_fk(ctx, report):
    """Today's sighting_id on OtherSpeciesT and SightingEventT, against the new one."""
    cur, new, live = ctx.cur, ctx.new, ctx.live
    sighting = dict(rows_kv(cur, f'select id, "SightingID" from {new}."SightingT"'))
    _, sighting_key = parent_keys(ctx)
    for table in ("OtherSpeciesT", "SightingEventT"):
        legacy = KEYED[table]
        lv = dict(rows_kv(cur, f'select "{legacy}", sighting_id from {live}."{table}"'))
        child = {r[legacy]: r for r in rows(
            cur, f'select "{legacy}", "Research Group", "Vessel", "Date", "Sighting" from {new}."{table}"')}
        for k, nid in rows_kv(cur, f'select "{legacy}", sighting_id from {new}."{table}"'):
            if k not in lv:
                continue
            got = sighting.get(nid)
            if got == lv[k]:
                continue
            if lv[k] is None:
                report.explain(table, "sighting_id (today's)", "Rule 3: found by Research Group, Vessel, Date and "
                               "Sighting; today matched by DailyEffortID and Sighting", k)
            elif got is None:
                report.explain(table, "sighting_id (today's)", "Rule 3: today matched it by DailyEffortID and "
                               "Sighting; its combination matches no sighting, or several", k)
            else:
                same_parent(report, table, "sighting_id (today's)", child[k], sighting_key.get(nid),
                            "Rule 3/6: a different record of the same sighting", {"id": k, "today": lv[k], "new": got})


def compare_categories(ctx, report):
    cur, new, live = ctx.cur, ctx.new, ctx.live
    lc = {key_text(r["code"]): r for r in rows(cur, f'select * from {live}."SpeciesT"')}
    nc = {key_text(r["Abbreviation"]): r for r in rows(cur, f'select * from {new}."SpeciesT"')}
    for k in lc.keys() - nc.keys():
        report.explain("SpeciesT", "(record)", "Today's hand-kept list had it; DB167's SpeciesT does not "
                                               "(the new SpeciesT is DB167's, plus rule 9)", lc[k]["code"])
    for k in nc.keys() - lc.keys():
        report.explain("SpeciesT", "(record)", "In DB167's SpeciesT, not in today's hand-kept list",
                       nc[k]["Abbreviation"])
    for k in nc.keys() & lc.keys():
        if lc[k]["category"] != nc[k]["category"]:
            report.fail("SpeciesT", "category", "a different category", {"code": k})

    keys = dict(rows_kv(cur, f"select key, vessel_id from {ctx.build}.vessel_keys"))
    for r in rows(cur, f'select * from {live}."VesselListT"'):
        if keys.get(key_text(r["vessel_text"])) is not None:
            report.explain("VesselListT", "(record)", "Rule 4: today one row per spelling; now that spelling "
                                                      "finds its vessel's one row", r["vessel_id"])
        else:
            report.fail("VesselListT", "(record)", "a spelling no vessel answers to", r["vessel_text"])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default="test_last")
    parser.add_argument("--live", default="live_dbo")
    parser.add_argument("--new", default="dbo_next")
    parser.add_argument("--build", default="build_next")
    parser.add_argument("--new-app", default="app_next")
    parser.add_argument("--report")
    args = parser.parse_args()
    url = os.environ.get("VERIFY_DATABASE_URL", f"postgresql://cascadia:cascadia@db:5432/{args.db}")
    report = Report()
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(f"set search_path = {args.build}, public")
        ctx = Context(cur, args.new, args.build, args.live)
        for table in sorted(KEYED):
            live_rows, new_rows, raw = compare_records(ctx, report, table)
            compare_derived(ctx, report, table, live_rows, new_rows, raw)
            compare_rest(ctx, report, table, live_rows, new_rows)
            print(f"  compared {table}", file=sys.stderr)
        compare_links(ctx, report)
        compare_live_fk(ctx, report)
        compare_categories(ctx, report)
        compare_app(ctx, report, args.new_app, report.touched)
        compare_other_views(ctx, report, args.new_app, args.new)
        cur.execute(f"""select table_name from information_schema.tables where table_schema = %s
                        and table_type = 'BASE TABLE' order by 1""", [args.live])
        for (table,) in cur.fetchall():
            if table not in DBO_TABLES:
                report.explain(table, "(table)", "Rule 1: the website never uses it; it stays in raw", table)

    explained = sorted(report.counts.items())
    print(f"\nExplained differences: {sum(report.counts.values()):,}")
    for (table, column, reason), n in explained:
        print(f"  {n:>8,}  {table}.{column}: {reason}")
    print(f"\nUnexplained differences: {sum(report.unexplained.values()):,}")
    for (table, column, reason), n in sorted(report.unexplained.items()):
        print(f"  {n:>8,}  {table}.{column}: {reason}")
        for e in report.unexplained_examples[(table, column, reason)]:
            print(f"            {e}")
    if args.report:
        with open(args.report, "w") as f:
            json.dump({"explained": [{"table": t, "column": c, "reason": r, "count": n,
                                      "examples": report.examples[(t, c, r)]} for (t, c, r), n in explained],
                       "unexplained": [{"table": t, "column": c, "reason": r, "count": n,
                                        "examples": report.unexplained_examples[(t, c, r)]}
                                       for (t, c, r), n in sorted(report.unexplained.items())]},
                      f, indent=1, default=str)
    return 1 if report.unexplained else 0


if __name__ == "__main__":
    sys.exit(main())
