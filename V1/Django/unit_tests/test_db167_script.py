"""The SQL Server script that puts the website's changes into DB167: what it
writes for each kind of change, how values are quoted, and that every write is
guarded so the script can be run again."""

import re
from datetime import datetime

from django.test import SimpleTestCase

from datahealth import db167_script as script
from datahealth.db167_script import Schema

SCHEMA = Schema(
    columns={
        "DailyEffortT": {"DailyEffortID": "integer", "Locality": "text", "Region": "text",
                         "Start Dec Lat": "double precision", "Finalized": "boolean",
                         "Date": "timestamp without time zone", "Start Time": "time without time zone",
                         "Total Distance": "numeric(10,3)", "Survey Date": "date"},
        "SightingT": {"SightingID": "integer", "Comments": "text", "Depth": "integer",
                      "Sighting_hash": "bytea", "Start Dec Long": "double precision", "Photos?": "boolean"},
        "OtherSpeciesT": {"OtherSpeciesID": "integer", "Class": "text", "Count": "integer"},
        "IdentificationT": {"IdentificationID": "integer", "Comments": "text"},
        "TrackT": {"TrackID": "integer", "EffortID": "integer", "TrackFileName": "text",
                   "SurveyDate": "date", "StartTime": "timestamp without time zone", "EndTime": "timestamp without time zone",
                   "Useable": "boolean", "Vessel": "text", "Research Group": "text"},
        "EffortCrewT": {"EffortCrewID": "integer", "CrewName": "text"},
    },
    keys={"DailyEffortT": "DailyEffortID", "SightingT": "SightingID", "OtherSpeciesT": "OtherSpeciesID",
          "IdentificationT": "IdentificationID", "TrackT": "TrackID", "EffortCrewT": "EffortCrewID"})

NOW = datetime(2026, 10, 20, 9, 30)


def entry(number, action, table, pk, changes=None, snapshot=None, legacy_pk=None, restored_by=None,
          comment=None, actor="Doug Sandilands"):
    return {"id": number, "at": datetime(2026, 9, 9, 14, 3), "actor": actor, "action": action, "table": table,
            "pk": str(pk), "legacy_pk": None if legacy_pk is None else str(legacy_pk), "changes": changes,
            "snapshot": snapshot, "comment": comment, "restored_by": restored_by}


def update(number, table, pk, column, old, new, legacy_pk=None, action="update"):
    return entry(number, action, table, pk, {column: {"old": old, "new": new}}, legacy_pk=legacy_pk)


def one(entries):
    return script.write(entries, SCHEMA, NOW)


def results(sql):
    """The (entry, result) pairs the script reports, in order."""
    found = re.findall(r"INSERT INTO #Report \(EntryID, Result, Detail\) VALUES \((\d+), N'([^']+)'", sql)
    return [(n, r) for n, r in found if r != "Error, Skipped"]      # what an error handler would report


class LiteralTests(SimpleTestCase):

    def test_null(self):
        self.assertEqual(script.literal(None, "text"), "NULL")
        self.assertEqual(script.literal(None, "integer"), "NULL")

    def test_text_is_unicode_and_doubles_apostrophes(self):
        self.assertEqual(script.literal("Neah Bay", "text"), "N'Neah Bay'")
        self.assertEqual(script.literal("O'Brien's Pt", "text"), "N'O''Brien''s Pt'")
        self.assertEqual(script.literal("Baie-Saint-Paul \u00e9t\u00e9", "text"), "N'Baie-Saint-Paul \u00e9t\u00e9'")

    def test_text_keeps_what_would_end_a_literal_or_a_comment_harmless(self):
        self.assertEqual(script.literal("'; DROP TABLE TrackT; --", "text"), "N'''; DROP TABLE TrackT; --'")
        self.assertEqual(script.literal("a\nb", "text"), "N'a\nb'")

    def test_numbers(self):
        self.assertEqual(script.literal(3816, "integer"), "3816")
        self.assertEqual(script.literal("3816", "integer"), "3816")
        self.assertEqual(script.literal(3816.0, "integer"), "3816")
        self.assertEqual(script.literal(-129.195, "double precision"), "-129.195E0")
        self.assertEqual(script.literal(1e-05, "double precision"), "1E-05")
        self.assertEqual(script.literal("42.125", "numeric(10,3)"), "42.125")

    def test_a_number_that_is_not_one_is_refused(self):
        for value, kind in [(3.5, "integer"), ("abc", "integer"), (float("nan"), "double precision"),
                            ("abc", "numeric(10,3)")]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    script.literal(value, kind)

    def test_booleans_are_bits(self):
        self.assertEqual(script.literal(True, "boolean"), "1")
        self.assertEqual(script.literal(False, "boolean"), "0")
        self.assertEqual(script.literal("f", "boolean"), "0")
        self.assertEqual(script.literal(True, "integer"), "1")

    def test_dates_and_times_are_the_form_sql_server_reads_in_every_language(self):
        self.assertEqual(script.literal("2026-05-17", "date"), "'2026-05-17'")
        self.assertEqual(script.literal("2026-05-17 08:00:00", "date"), "'2026-05-17'")
        self.assertEqual(script.literal("2026-05-17", "timestamp without time zone"), "'2026-05-17T00:00:00'")
        self.assertEqual(script.literal("2026-05-17 08:05:09", "timestamp without time zone"), "'2026-05-17T08:05:09'")
        self.assertEqual(script.literal("2026-05-17T08:05:09.123456", "timestamp without time zone"),
                         "'2026-05-17T08:05:09.123'")
        self.assertEqual(script.literal("2026-05-17 8:05", "timestamp without time zone"), "'2026-05-17T8:05:00'")
        self.assertEqual(script.literal("08:15:00", "time without time zone"), "'08:15:00'")

    def test_a_date_that_is_not_one_is_refused(self):
        for value, kind in [("yesterday", "date"), ("2026-13-45", "timestamp without time zone"),
                            ("noon", "time without time zone")]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    script.literal(value, kind)

    def test_names_are_bracketed(self):
        self.assertEqual(script.ident("Sub-area"), "[Sub-area]")
        self.assertEqual(script.ident("Odd]Name"), "[Odd]]Name]")


class ConditionTests(SimpleTestCase):

    def test_a_value_is_compared_exactly(self):
        self.assertEqual(script.holds("Locality", "text", "Neah Bay"),
                         "([Locality] IS NOT NULL AND CAST([Locality] AS nvarchar(max)) "
                         "COLLATE Latin1_General_100_BIN2 = N'Neah Bay')")
        self.assertEqual(script.holds("Locality", "text", None), "[Locality] IS NULL")
        self.assertEqual(script.holds("Depth", "integer", 12), "([Depth] IS NOT NULL AND [Depth] = 12)")

    def test_an_old_text_value_ignores_capitals_and_spaces(self):
        sql = script.held("Locality", "text", "Seiku")
        self.assertIn("LTRIM(RTRIM(CAST([Locality] AS nvarchar(max))))", sql)
        self.assertIn("COLLATE Latin1_General_100_CI_AS = N'Seiku'", sql)

    def test_an_empty_old_value_is_the_same_as_NULL(self):
        for value in (None, "", "  "):
            with self.subTest(value=value):
                self.assertEqual(script.held("Locality", "text", value),
                                 "NULLIF(LTRIM(RTRIM(CAST([Locality] AS nvarchar(max)))), N'') IS NULL")

    def test_other_types_are_compared_exactly_either_way(self):
        self.assertEqual(script.held("Depth", "integer", 12), script.holds("Depth", "integer", 12))
        self.assertEqual(script.held("Depth", "integer", None), "[Depth] IS NULL")


class UpdateTests(SimpleTestCase):

    def test_an_update_writes_the_new_value_where_the_old_one_is_still_held(self):
        sql = one([update(12, "DailyEffortT", "-5171839947084969536", "Locality", "Seiku", "Sekiu", legacy_pk=3816)])
        self.assertIn("UPDATE [dbo].[DailyEffortT] SET [Locality] = N'Sekiu'", sql)
        self.assertIn("WHERE [DailyEffortID] = 3816 AND ", sql)
        self.assertIn("COLLATE Latin1_General_100_CI_AS = N'Seiku'", sql)
        self.assertEqual(results(sql), [("12", "Applied"), ("12", "Already Applied"), ("12", "Conflict, Skipped")])

    def test_the_record_is_found_by_its_legacy_id_not_the_hashed_id(self):
        sql = one([update(12, "DailyEffortT", "5171839947084969536", "Locality", "a", "b", legacy_pk=3816)])
        self.assertNotIn("5171839947084969536", sql.split("CREATE TABLE #Report")[1].split("-- Entry")[1].split("\n", 1)[1])

    def test_an_old_NULL_is_matched_with_IS_NULL(self):
        sql = one([update(1, "SightingT", "9", "Depth", None, 40, legacy_pk=11)])
        self.assertIn("UPDATE [dbo].[SightingT] SET [Depth] = 40", sql)
        self.assertIn("WHERE [SightingID] = 11 AND [Depth] IS NULL AND NOT ([Depth] IS NOT NULL AND [Depth] = 40);", sql)

    def test_a_new_NULL_is_written_as_NULL(self):
        sql = one([update(1, "SightingT", "9", "Depth", 40, None, legacy_pk=11)])
        self.assertIn("SET [Depth] = NULL", sql)
        self.assertIn("AND NOT [Depth] IS NULL;", sql)
        self.assertIn("WHERE [SightingID] = 11 AND ([Depth] IS NOT NULL AND [Depth] = 40)", sql)

    def test_an_apostrophe_in_text_cannot_end_the_literal(self):
        sql = one([update(1, "DailyEffortT", "9", "Locality", "Smith's Pt", "O'Brien's Pt", legacy_pk=5)])
        self.assertIn("SET [Locality] = N'O''Brien''s Pt'", sql)
        self.assertIn("= N'Smith''s Pt'", sql)

    def test_each_field_of_an_entry_is_its_own_write_and_report(self):
        e = entry(6, "update", "DailyEffortT", "9", {"Locality": {"old": "a", "new": "b"},
                                                    "Region": {"old": "c", "new": "d"}}, legacy_pk=27798)
        sql = one([e])
        self.assertEqual(sql.count("UPDATE [dbo].[DailyEffortT]"), 2)
        self.assertIn("SET [Locality] = N'b'", sql)
        self.assertIn("SET [Region] = N'd'", sql)
        self.assertEqual(len(results(sql)), 6)

    def test_associate_and_dissociate_write_the_effort_id(self):
        sql = one([update(1, "TrackT", 94, "EffortID", None, 24093, action="associate"),
                   update(2, "TrackT", 94, "EffortID", 24093, None, action="dissociate")])
        # The match is undone straight after, so only the end of it is written.
        self.assertEqual(sql.count("UPDATE"), 1)
        self.assertIn("UPDATE [dbo].[TrackT] SET [EffortID] = NULL", sql)
        self.assertIn("WHERE [TrackID] = 94 AND ([EffortID] IS NULL OR ([EffortID] IS NOT NULL AND [EffortID] = 24093)) AND NOT", sql)
        self.assertEqual([r for _, r in results(sql)][:1], ["Superseded"])

    def test_a_match_is_written_when_nothing_undoes_it(self):
        sql = one([update(1, "TrackT", 94, "EffortID", None, 24093, action="associate")])
        self.assertIn("UPDATE [dbo].[TrackT] SET [EffortID] = 24093", sql)
        self.assertIn("WHERE [TrackID] = 94 AND [EffortID] IS NULL AND NOT", sql)

    def test_a_field_is_superseded_only_by_a_change_to_the_same_field_of_the_same_record(self):
        sql = one([update(1, "TrackT", 94, "EffortID", None, 5, action="associate"),
                   update(2, "TrackT", 94, "Vessel", None, "ROB"),
                   update(3, "TrackT", 95, "EffortID", None, 6, action="associate")])
        self.assertEqual([r for _, r in results(sql) if r == "Superseded"], [])
        self.assertEqual(sql.count("UPDATE"), 3)

    def test_fields_the_website_works_out_are_left_out(self):
        e = entry(139, "associate", "TrackT", 94, {"EffortID": {"old": None, "new": 24093},
                                                  "track_status": {"old": "unassociated", "new": "available"},
                                                  "daily_effort_id": {"old": None, "new": 8}})
        sql = one([e])
        self.assertEqual(sql.count("UPDATE"), 1)
        self.assertNotIn("track_status", sql.split("-- Entry")[1].split("INSERT INTO #Report")[0])
        self.assertEqual([r for _, r in results(sql)], ["Applied", "Already Applied", "Conflict, Skipped"])

    def test_a_change_to_a_value_with_no_column_in_DB167_is_reported_not_applicable(self):
        e = entry(137, "update", "SightingT", "9", {"Comments": {"old": None, "new": "x"},
                                                   "depth_m": {"old": None, "new": 123.45}}, legacy_pk=11)
        sql = one([e])
        self.assertEqual(sql.count("UPDATE"), 1)
        self.assertIn("(137, N'Not Applicable', N'SightingT 11, depth_m: worked out by the website", sql)

    def test_an_entry_of_only_such_fields_is_not_applicable(self):
        e = entry(5, "upload", "TrackT", 94, {"geom": {"old": None, "new": "x"}, "track_status": {"old": "a", "new": "b"}})
        sql = one([e])
        self.assertNotIn("UPDATE", sql)
        self.assertEqual(results(sql), [("5", "Not Applicable")])
        e["action"] = "update"
        self.assertEqual(results(one([e])), [("5", "Not Applicable")])

    def test_a_computed_column_is_never_written(self):
        e = entry(1, "update", "SightingT", "9", {"Sighting_hash": {"old": "a", "new": "b"}}, legacy_pk=11)
        self.assertNotIn("UPDATE", one([e]))

    def test_a_field_changed_twice_is_already_applied_once_both_are_written(self):
        sql = one([update(1, "DailyEffortT", "9", "Locality", "A", "B", legacy_pk=5),
                   update(2, "DailyEffortT", "9", "Locality", "B", "C", legacy_pk=5)])
        first, second = sql.split("-- Entry 2")
        self.assertNotIn("UPDATE", first)                           # written over by entry 2
        self.assertEqual(results(first), [("1", "Superseded")])
        # Entry 2 starts from where either of them did, and is done once DB167 holds C.
        self.assertIn("= N'A'", second.split("WHERE")[1].split("AND NOT")[0])
        self.assertIn("= N'B'", second.split("WHERE")[1].split("AND NOT")[0])
        self.assertIn("= N'C'", second.split("ELSE IF EXISTS")[1])

    def test_an_entry_with_no_legacy_id_for_a_hashed_table_is_skipped_and_said_so(self):
        sql = one([update(1, "SightingT", "6359275879002753306", "Comments", "a", "b")])
        self.assertNotIn("UPDATE", sql)
        self.assertEqual(results(sql), [("1", "Conflict, Skipped")])

    def test_a_value_that_cannot_be_written_skips_only_its_entry(self):
        sql = one([update(1, "SightingT", "9", "Depth", 40, "forty", legacy_pk=11),
                   update(2, "SightingT", "9", "Depth", 40, 41, legacy_pk=12)])
        self.assertEqual([r for r in results(sql)][:1], [("1", "Conflict, Skipped")])
        self.assertIn("SET [Depth] = 41", sql)

    def test_dates_and_booleans_and_floats_are_typed_by_their_column(self):
        sql = one([update(1, "DailyEffortT", "9", "Date", "2020-07-01T00:00:00", "2020-07-02 00:00:00", legacy_pk=5),
                   update(2, "DailyEffortT", "9", "Finalized", False, True, legacy_pk=5),
                   update(3, "DailyEffortT", "9", "Start Dec Lat", 47.1, 47.25, legacy_pk=5)])
        self.assertIn("SET [Date] = '2020-07-02T00:00:00'", sql)
        self.assertIn("SET [Finalized] = 1", sql)
        self.assertIn("SET [Start Dec Lat] = 47.25E0", sql)


class TrackTimeTests(SimpleTestCase):
    """The website keeps a track's StartTime and EndTime in UTC and DB167 keeps
    them in Pacific local time, so the script writes, and compares with, Pacific."""

    def create(self, start="2026-08-26 16:21:51", end="2026-08-27 02:08:03"):
        return entry(115, "create", "TrackT", 1588, {
            "TrackID": {"old": None, "new": 1588}, "TrackFileName": {"old": None, "new": "a.csv"},
            "StartTime": {"old": None, "new": start}, "EndTime": {"old": None, "new": end}})

    def read(self, made):
        """The entry as read_entries leaves it, then as the script writes it."""
        script._track_times_as_db167_holds(made)
        return one([made])

    def test_a_created_track_is_written_with_the_pacific_equivalent_of_its_utc_times(self):
        made = self.create()
        sql = self.read(made)
        self.assertIn("'2026-08-26T09:21:51'", sql)          # 16:21 UTC is 09:21 PDT
        self.assertIn("'2026-08-26T19:08:03'", sql)          # 02:08 UTC the next day is 19:08 PDT the day before
        self.assertNotIn("2026-08-26T16:21:51", sql)
        self.assertEqual(made["changes"]["StartTime"]["new"], "2026-08-26 09:21:51")

    def test_an_update_writes_and_checks_in_pacific(self):
        made = update(116, "TrackT", 1588, "StartTime", "2026-01-05 18:00:00", "2026-01-05 19:30:15")
        sql = self.read(made)
        self.assertIn("SET [StartTime] = '2026-01-05T11:30:15'", sql)       # PST, 8 hours behind
        self.assertIn("[StartTime] = '2026-01-05T10:00:00'", sql)           # the old value DB167 must still hold
        self.assertNotIn("19:30:15", sql)

    def test_a_deleted_tracks_rows_are_compared_and_restored_in_pacific(self):
        row = {"TrackID": 1588, "TrackFileName": "a.csv", "StartTime": "2026-08-26 16:21:51"}
        made = entry(117, "delete", "TrackT", 1588, snapshot={"TrackT": [row]})
        sql = self.read(made)
        self.assertIn("'2026-08-26T09:21:51'", sql)
        self.assertNotIn("16:21:51", sql)

    def test_daylight_saving_is_followed_at_both_changes(self):
        for utc, pacific in (("2026-03-08 09:59:59", "2026-03-08 01:59:59"),     # the last second before clocks go forward
                             ("2026-03-08 10:00:00", "2026-03-08 03:00:00"),     # the first after
                             ("2026-11-01 08:59:59", "2026-11-01 01:59:59"),     # the first 01:59 (PDT)
                             ("2026-11-01 09:00:00", "2026-11-01 01:00:00"),     # clocks go back: 01:00 again (PST)
                             ("2026-11-01 10:00:00", "2026-11-01 02:00:00"),
                             ("2026-07-01 00:00:00", "2026-06-30 17:00:00"),
                             ("2026-12-01 00:00:00", "2026-11-30 16:00:00")):
            self.assertEqual(script.pacific_from_utc(utc), pacific, utc)
        self.assertEqual(script.pacific_from_utc("2026-08-26T16:21:51.250"), "2026-08-26 09:21:51.250")

    def test_only_a_tracks_times_are_changed(self):
        other = entry(9, "update", "DailyEffortT", "9", {"Start Time": {"old": "01:00:00", "new": "02:00:00"}}, legacy_pk=5)
        script._track_times_as_db167_holds(other)
        self.assertEqual(other["changes"], {"Start Time": {"old": "01:00:00", "new": "02:00:00"}})
        track = update(10, "TrackT", 1, "Useable", True, False)
        script._track_times_as_db167_holds(track)
        self.assertEqual(track["changes"], {"Useable": {"old": True, "new": False}})


class EffortNumberTests(SimpleTestCase):
    """A track is matched by the Effort's hashed id, which holds when DB167 renumbers the
    Effort; the script writes the Effort's number now, not the one the entry kept."""

    HASH = 6647073096327391983

    class Cursor:
        def __init__(self, rows):
            self.rows, self.asked = rows, None

        def execute(self, sql, params):
            self.asked = params

        def fetchall(self):
            return self.rows

    def create(self):
        return entry(115, "create", "TrackT", 1588, {
            "TrackID": {"old": None, "new": 1588}, "TrackFileName": {"old": None, "new": "a.csv"},
            "EffortID": {"old": None, "new": 28148}, "daily_effort_id": {"old": None, "new": self.HASH}})

    def read(self, made, numbers):
        script._efforts_as_db167_holds(made, numbers)
        return one([made])

    def test_a_created_track_is_given_the_effort_number_now_not_the_one_it_kept(self):
        sql = self.read(self.create(), {self.HASH: 29152})
        self.assertIn("29152", sql)
        self.assertNotIn("28148", sql)

    def test_the_entrys_own_number_is_used_only_if_the_effort_cannot_be_found(self):
        sql = self.read(self.create(), {})
        self.assertIn("28148", sql)

    def test_a_match_and_an_unmatch_are_written_and_checked_with_the_number_now(self):
        match = entry(116, "associate", "TrackT", 1588, {"EffortID": {"old": None, "new": 28148},
                                                         "daily_effort_id": {"old": None, "new": self.HASH}})
        sql = self.read(match, {self.HASH: 29152})
        self.assertIn("SET [EffortID] = 29152", sql)
        self.assertNotIn("28148", sql)
        unmatch = entry(117, "dissociate", "TrackT", 1588, {"EffortID": {"old": 28148, "new": None},
                                                            "daily_effort_id": {"old": self.HASH, "new": None}})
        sql = self.read(unmatch, {self.HASH: 29152})
        self.assertIn("[EffortID] = 29152", sql)
        self.assertNotIn("28148", sql)

    def test_the_rows_a_delete_kept_are_compared_with_the_number_now(self):
        row = {"TrackID": 1588, "TrackFileName": "a.csv", "EffortID": 28148, "daily_effort_id": self.HASH}
        made = entry(118, "delete", "TrackT", 1588, snapshot={"TrackT": [row]})
        sql = self.read(made, {self.HASH: 29152})
        self.assertIn("29152", sql)
        self.assertNotIn("28148", sql)

    def test_the_lookup_asks_once_for_every_effort_the_entries_name(self):
        entries = [self.create(), entry(1, "update", "DailyEffortT", "1", {"Locality": {"old": "A", "new": "B"}})]
        cursor = self.Cursor([(self.HASH, 29152)])
        self.assertEqual(script.effort_numbers(cursor, entries), {self.HASH: 29152})
        self.assertEqual(cursor.asked, [[self.HASH]])
        self.assertEqual(script.effort_numbers(self.Cursor([]), [entries[1]]), {})


class CreateTests(SimpleTestCase):

    CREATE = entry(115, "create", "TrackT", 1588, {
        "TrackID": {"old": None, "new": 1588}, "TrackFileName": {"old": None, "new": "20260826-ROB's.csv"},
        "SurveyDate": {"old": None, "new": "2026-08-26"}, "StartTime": {"old": None, "new": "2026-08-26 09:00:00"},
        "Useable": {"old": None, "new": True}, "EffortID": {"old": None, "new": 28148},
        "Vessel": {"old": None, "new": "ROB"}, "geom": {"old": None, "new": "SRID=4326;MULTILINESTRING((0 0,1 1))"},
        "track_status": {"old": None, "new": "available"}, "daily_effort_id": {"old": None, "new": 5}},
        snapshot={"uploaded_object": "20260826-ROB's.csv"})

    def test_a_track_is_added_with_the_trackid_the_website_gave_it(self):
        sql = one([self.CREATE])
        self.assertIn("IF NOT EXISTS (SELECT 1 FROM [dbo].[TrackT] WHERE [TrackID] = 1588)", sql)
        self.assertIn("SET IDENTITY_INSERT [dbo].[TrackT] ON;", sql)
        self.assertIn("SET IDENTITY_INSERT [dbo].[TrackT] OFF;", sql)
        insert = sql.split("INSERT INTO [dbo].[TrackT] ")[1].split(";")[0]
        self.assertIn("([TrackID], [EffortID], [TrackFileName], [SurveyDate], [StartTime], [Useable], [Vessel])", insert)
        self.assertIn("VALUES (1588, 28148, N'20260826-ROB''s.csv', '2026-08-26', '2026-08-26T09:00:00', 1, N'ROB')", insert)

    def test_only_columns_DB167_has_are_written(self):
        insert = one([self.CREATE]).split("INSERT INTO [dbo].[TrackT] ")[1].split(";")[0]
        for name in ("geom", "track_status", "daily_effort_id"):
            self.assertNotIn(name, insert)

    def test_the_identity_insert_is_turned_off_again(self):
        sql = one([self.CREATE])
        self.assertLess(sql.index("IDENTITY_INSERT [dbo].[TrackT] ON"), sql.index("IDENTITY_INSERT [dbo].[TrackT] OFF"))
        self.assertLess(sql.index("IDENTITY_INSERT [dbo].[TrackT] OFF"), sql.index("N'Applied'"))

    def test_the_same_file_under_that_trackid_is_the_same_track(self):
        sql = one([self.CREATE])
        again = sql.split("ELSE IF EXISTS")[1].split("INSERT")[0]
        self.assertIn("[TrackID] = 1588 AND", again)
        self.assertIn("= N'20260826-ROB''s.csv'", again)
        self.assertEqual([r for _, r in results(sql)], ["Applied", "Already Applied", "Conflict, Skipped"])

    def test_a_trackid_held_by_another_file_is_a_conflict_not_overwritten(self):
        sql = one([self.CREATE])
        self.assertEqual(sql.count("UPDATE"), 0)
        self.assertEqual(sql.count("DELETE"), 0)
        self.assertIn("DB167 already uses this TrackID for a different TrackFileName", sql)

    def test_a_record_in_a_table_DB167_numbers_itself_has_no_legacy_id_to_keep(self):
        sql = one([entry(1, "create", "SightingT", 5, {"Comments": {"old": None, "new": "x"}})])
        self.assertNotIn("INSERT INTO [dbo]", sql)
        self.assertEqual(results(sql), [("1", "Not Applicable")])


def sighting_snapshot():
    return {
        "SightingT": [{"id": 6359275879002753306, "SightingID": 18, "Comments": None, "Depth": 93,
                       "Start Dec Long": -117.3395, "Photos?": True, "Sighting_hash": "\\x29", "depth_m": 93.0,
                       "geom": {"type": "Point"}}],
        "__order__": ["IdentificationT", "OtherSpeciesT"],
        "OtherSpeciesT": [{"id": 8, "OtherSpeciesID": 269, "Class": "Bird", "Count": 50}],
        "IdentificationT": [{"id": 9, "IdentificationID": 256, "Comments": "it's one"}],
    }


class DeleteTests(SimpleTestCase):

    def delete(self):
        return entry(140, "delete", "SightingT", "6359275879002753306", snapshot=sighting_snapshot(), legacy_pk=18)

    def test_children_are_deleted_before_the_record(self):
        sql = one([self.delete()])
        deletes = re.findall(r"DELETE FROM \[dbo\]\.\[(\w+)\]", sql)
        self.assertEqual(deletes, ["OtherSpeciesT", "IdentificationT", "SightingT"])

    def test_every_row_is_found_by_its_own_legacy_id(self):
        sql = one([self.delete()])
        self.assertIn("DELETE FROM [dbo].[OtherSpeciesT] WHERE [OtherSpeciesID] = 269 AND ", sql)
        self.assertIn("DELETE FROM [dbo].[IdentificationT] WHERE [IdentificationID] = 256 AND ", sql)
        self.assertIn("DELETE FROM [dbo].[SightingT] WHERE [SightingID] = 18 AND ", sql)
        self.assertNotIn("6359275879002753306", sql.split("CREATE TABLE #Report")[1].split("-- Entry")[1].split("\n", 1)[1])

    def test_each_delete_is_guarded_by_what_the_website_kept(self):
        sql = one([self.delete()])
        delete = re.search(r"DELETE FROM \[dbo\]\.\[SightingT\] WHERE (.*?);\n", sql).group(1)
        self.assertIn("[Comments]", delete)           # a NULL it kept
        self.assertIn("NULLIF(LTRIM(RTRIM(CAST([Comments] AS nvarchar(max)))), N'') IS NULL", delete)
        self.assertIn("([Depth] IS NOT NULL AND [Depth] = 93)", delete)
        self.assertIn("([Start Dec Long] IS NOT NULL AND [Start Dec Long] = -117.3395E0)", delete)
        self.assertIn("([Photos?] IS NOT NULL AND [Photos?] = 1)", delete)

    def test_columns_DB167_does_not_have_or_computes_are_not_compared(self):
        delete = re.search(r"DELETE FROM \[dbo\]\.\[SightingT\] WHERE (.*?);\n", one([self.delete()])).group(1)
        for name in ("depth_m", "geom", "Sighting_hash", "[id]"):
            self.assertNotIn(name, delete)

    def test_a_record_already_gone_is_already_applied_and_nothing_is_forced(self):
        sql = one([self.delete()])
        self.assertIn("\n    IF NOT (EXISTS", sql.split("-- Entry 140")[1])
        self.assertEqual([r for _, r in results(sql)], ["Already Applied", "Conflict, Skipped", "Applied"])

    def test_a_row_that_has_changed_stops_the_whole_delete(self):
        sql = one([self.delete()])
        changed = sql.split("ELSE IF ")[1].split("\n")[0]
        self.assertEqual(changed.count("EXISTS"), 3)
        self.assertEqual(changed.count("AND NOT ("), 3)
        self.assertLess(sql.index("ELSE IF "), sql.index("DELETE FROM"))

    def test_an_apostrophe_in_a_kept_value_is_escaped(self):
        self.assertIn("N'it''s one'", one([self.delete()]))

    def test_a_delete_with_no_copy_is_skipped(self):
        sql = one([entry(1, "delete", "TrackT", 842)])
        self.assertNotIn("DELETE", sql)
        self.assertEqual(results(sql), [("1", "Conflict, Skipped")])

    def test_a_delete_in_a_table_keyed_by_its_primary_key(self):
        e = entry(80, "delete", "EffortCrewT", 260, snapshot={"EffortCrewT": [{"EffortCrewID": 260, "CrewName": None}]})
        sql = one([e])
        self.assertIn("DELETE FROM [dbo].[EffortCrewT] WHERE [EffortCrewID] = 260 AND ", sql)

    def test_a_snapshot_without_its_order_still_deletes_children_first(self):
        snapshot = sighting_snapshot()
        del snapshot["__order__"]
        sql = one([entry(1, "delete", "SightingT", "9", snapshot=snapshot, legacy_pk=18)])
        self.assertEqual(re.findall(r"DELETE FROM \[dbo\]\.\[(\w+)\]", sql)[-1], "SightingT")


class RestoreTests(SimpleTestCase):

    def restore(self):
        return entry(9, "restore", "SightingT", "9", snapshot=sighting_snapshot(), legacy_pk=18)

    def test_a_kept_record_is_put_back_record_first_with_its_own_ids(self):
        sql = one([self.restore()])
        inserts = re.findall(r"INSERT INTO \[dbo\]\.\[(\w+)\]", sql)
        self.assertEqual(inserts[:1] + [i for i in inserts if i != "SightingT"],
                         ["SightingT", "IdentificationT", "OtherSpeciesT"])
        self.assertIn("SET IDENTITY_INSERT [dbo].[SightingT] ON;", sql)
        self.assertIn("SET IDENTITY_INSERT [dbo].[SightingT] OFF;", sql)

    def test_it_is_done_only_if_none_of_its_rows_are_there(self):
        sql = one([self.restore()])
        self.assertIn("IF NOT EXISTS (SELECT 1 FROM [dbo].[SightingT] WHERE [SightingID] = 18) AND "
                      "NOT EXISTS (SELECT 1 FROM [dbo].[IdentificationT]", sql)
        self.assertEqual([r for _, r in results(sql)], ["Applied", "Already Applied", "Conflict, Skipped"])

    def test_only_columns_DB167_has_are_put_back(self):
        insert = re.search(r"INSERT INTO \[dbo\]\.\[SightingT\] \((.*?)\)", one([self.restore()])).group(1)
        self.assertEqual(insert, "[SightingID], [Comments], [Depth], [Start Dec Long], [Photos?]")

    def test_a_restore_that_only_changed_fields_is_an_update(self):
        e = entry(8, "restore", "SightingT", "9", {"Depth": {"old": 5, "new": 4}}, legacy_pk=18)
        sql = one([e])
        self.assertIn("UPDATE [dbo].[SightingT] SET [Depth] = 4", sql)
        self.assertNotIn("IDENTITY_INSERT", sql)


class KindsOfEntryTests(SimpleTestCase):

    def test_an_upload_writes_nothing_because_DB167_holds_only_file_names(self):
        sql = one([entry(5, "upload", "TrackT", 94, {"length_nm": {"old": None, "new": 3.2}})])
        self.assertEqual(results(sql), [("5", "Not Applicable")])
        self.assertNotIn("UPDATE", sql)
        self.assertNotIn("INSERT INTO [dbo]", sql)
        self.assertIn("holds only the names of track files", sql)

    def test_a_file_edit_writes_nothing(self):
        sql = one([entry(5, "edit_file", "TrackT", 94, {"TrackFileName": {"old": "a.csv", "new": "b.csv"}})])
        self.assertEqual(results(sql), [("5", "Not Applicable")])
        self.assertNotIn("UPDATE", sql)

    def test_an_action_not_known_is_not_applicable(self):
        sql = one([entry(5, "teleport", "TrackT", 94, {"EffortID": {"old": 1, "new": 2}})])
        self.assertEqual(results(sql), [("5", "Not Applicable")])
        self.assertNotIn("UPDATE", sql)

    def test_a_table_DB167_does_not_have_is_not_applicable(self):
        sql = one([update(5, "NoSuchT", 1, "x", 1, 2)])
        self.assertEqual(results(sql), [("5", "Not Applicable")])

    def test_an_entry_the_old_restore_put_back_cancels_out_with_its_restore(self):
        both = one([{**update(1, "SightingT", "9", "Depth", 1, 2, legacy_pk=11), "restored_by": 2},
                    entry(2, "restore", "SightingT", "9", {"Depth": {"old": 2, "new": 1}}, legacy_pk=11)])
        self.assertEqual(results(both), [("1", "Not Applicable"), ("2", "Not Applicable")])
        self.assertNotIn("UPDATE", both)


class WholeScriptTests(SimpleTestCase):

    ENTRIES = [
        update(1, "DailyEffortT", "9", "Locality", "a", "b", legacy_pk=5),
        entry(2, "upload", "TrackT", 94, {"geom": {"old": None, "new": "x"}}),
        update(3, "TrackT", 94, "EffortID", None, 24093, action="associate"),
    ]

    def test_it_is_one_transaction_that_commits_what_worked(self):
        sql = one(self.ENTRIES)
        self.assertEqual(sql.count("BEGIN TRAN;"), 1)
        self.assertEqual(sql.count("COMMIT;"), 1)
        self.assertIn("IF XACT_STATE() = 1 COMMIT;\nRETURN;", sql)
        self.assertNotIn("\nGO", sql)

    def test_a_failure_is_handled_by_the_entry_not_by_aborting_the_transaction(self):
        sql = one(self.ENTRIES)
        # With XACT_ABORT on, one error would make the whole transaction unusable.
        self.assertIn("SET XACT_ABORT OFF;", sql)
        self.assertNotIn("XACT_ABORT ON", sql)
        self.assertLess(sql.index("SET XACT_ABORT OFF;"), sql.index("BEGIN TRAN;"))

    def test_it_keeps_a_report_and_prints_it_before_it_commits(self):
        sql = one(self.ENTRIES)
        self.assertIn("CREATE TABLE #Report (", sql)
        self.assertLess(sql.index("CREATE TABLE #Report"), sql.index("-- Entry 1,"))
        self.assertLess(sql.index("FROM #Report ORDER BY Seq;"), sql.index("COMMIT;"))
        self.assertIn("GROUP BY Result", sql)

    def test_entries_are_written_in_the_order_they_were_made(self):
        sql = one(self.ENTRIES)
        positions = [sql.index(f"-- Entry {n},") for n in (1, 2, 3)]
        self.assertEqual(positions, sorted(positions))

    def test_it_sets_what_computed_and_indexed_columns_need(self):
        sql = one(self.ENTRIES)
        self.assertIn("SET QUOTED_IDENTIFIER ON;", sql)
        self.assertIn("SET ANSI_NULLS ON;", sql)
        self.assertIn("SET DATEFORMAT ymd;", sql)

    def test_the_same_log_gives_the_same_script(self):
        self.assertEqual(one(self.ENTRIES), one(self.ENTRIES))

    def test_every_write_is_guarded_so_a_second_run_changes_nothing(self):
        entries = self.ENTRIES + [CreateTests.CREATE, DeleteTests.delete(DeleteTests()),
                                  RestoreTests.restore(RestoreTests())]
        sql = one(entries)
        for statement in re.findall(r"^UPDATE .*?;$", sql, re.S | re.M):
            self.assertRegex(statement, r"WHERE \[\w+\] = \d+ AND ")
            self.assertIn("AND NOT ", statement)        # never rewrites a value that is already the new one
        for statement in re.findall(r"^DELETE .*?;$", sql, re.S | re.M):
            self.assertIn(" AND ", statement)
        # Every insert sits in a block that first checked the row is not there.
        for block in re.findall(r"^ *IF NOT EXISTS .*?^ *END\n", sql, re.S | re.M):
            self.assertIn("INSERT INTO [dbo]", block)
        self.assertEqual(sql.count("INSERT INTO [dbo]"), len(re.findall(r"^ {8}INSERT INTO \[dbo\]", sql, re.M)))

    def test_what_a_person_wrote_cannot_break_out_of_a_comment(self):
        e = entry(1, "update", "DailyEffortT", "9", {"Locality": {"old": "a", "new": "b"}}, legacy_pk=5,
                  comment="Fixed it.\nDROP TABLE TrackT; /* then */ --", actor="Sam\nO'Neil")
        sql = one([e])
        heading = [line for line in sql.splitlines() if line.startswith("-- Entry 1,")]
        self.assertEqual(len(heading), 1)
        self.assertNotIn("DROP TABLE", "\n".join(line for line in sql.splitlines() if not line.startswith("--")))
        self.assertNotIn("*/", heading[0])

    def test_an_empty_log_is_a_script_that_does_nothing(self):
        sql = one([])
        self.assertIn("no entries", sql)
        self.assertEqual(results(sql), [])
        self.assertIn("IF XACT_STATE() = 1 COMMIT;", sql)

    def test_the_file_is_named_for_when_it_was_made(self):
        self.assertEqual(script.filename(NOW), "Cascadia-DB167-Migration-2026-10-20-0930.sql")

    def test_no_text_claims_a_file_was_imported_from_DB167(self):
        sql = one(self.ENTRIES + [CreateTests.CREATE])
        self.assertNotRegex(sql.lower(), r"imported from db167")
        self.assertNotIn("\u2014", sql)
        self.assertNotIn("\u2192", sql)


class UnitOfWorkTests(SimpleTestCase):
    """Each entry that writes is its own unit: a savepoint, and a handler."""

    TRACK = entry(1, "create", "TrackT", 1588, {"TrackID": {"old": None, "new": 1588},
                                                "TrackFileName": {"old": None, "new": "a.csv"}})

    def units(self, sql):
        return re.findall(r"^BEGIN TRY\n(.*?)^END CATCH;", sql, re.S | re.M)

    def test_every_entry_that_writes_is_between_a_savepoint_and_a_handler(self):
        sql = one([update(1, "SightingT", "9", "Depth", 1, 2, legacy_pk=11), self.TRACK,
                   entry(3, "delete", "EffortCrewT", 260, snapshot={"EffortCrewT": [{"EffortCrewID": 260}]})])
        units = self.units(sql)
        self.assertEqual(len(units), 3)
        for unit in units:
            self.assertTrue(unit.startswith("    SAVE TRANSACTION Entry;\n"))
            self.assertIn("END TRY\nBEGIN CATCH\n", unit)

    def test_an_entry_that_writes_nothing_has_no_handler(self):
        sql = one([entry(5, "upload", "TrackT", 94, {"geom": {"old": None, "new": "x"}}),
                   update(6, "SightingT", "9", "depth_m", None, 1, legacy_pk=11)])
        self.assertNotIn("BEGIN TRY", sql)

    def test_the_handler_undoes_just_that_entry_and_reports_the_error(self):
        handler = self.units(one([self.TRACK]))[0].split("BEGIN CATCH\n")[1]
        self.assertIn("SET @ErrorNumber = ERROR_NUMBER(); SET @ErrorMessage = ERROR_MESSAGE();", handler)
        self.assertIn("IF XACT_STATE() <> 1 BEGIN SET @FailedEntry = 1; SET @FailedWhat = N'create TrackT 1588'; GOTO Doomed; END", handler)
        self.assertLess(handler.index("GOTO Doomed"), handler.index("ROLLBACK TRANSACTION Entry;"))
        self.assertLess(handler.index("ROLLBACK TRANSACTION Entry;"), handler.index("N'Error, Skipped'"))
        self.assertIn("(1, N'Error, Skipped', LEFT(N'create TrackT 1588: error ' + CAST(@ErrorNumber AS "
                      "nvarchar(20)) + N', ' + @ErrorMessage, 400))", handler)

    def test_IDENTITY_INSERT_is_turned_off_however_a_create_ends(self):
        handler = self.units(one([self.TRACK]))[0].split("BEGIN CATCH\n")[1]
        self.assertIn("SET IDENTITY_INSERT [dbo].[TrackT] OFF;", handler)
        self.assertLess(handler.index("IDENTITY_INSERT"), handler.index("ROLLBACK"))

    def test_and_however_a_restore_ends_for_every_table_it_turned_on(self):
        handler = self.units(one([RestoreTests().restore()]))[0].split("BEGIN CATCH\n")[1]
        for table in ("SightingT", "IdentificationT", "OtherSpeciesT"):
            self.assertIn(f"SET IDENTITY_INSERT [dbo].[{table}] OFF;", handler)

    def test_an_update_has_no_identity_insert_to_turn_off(self):
        handler = self.units(one([update(1, "SightingT", "9", "Depth", 1, 2, legacy_pk=11)]))[0].split("BEGIN CATCH\n")[1]
        self.assertNotIn("IDENTITY_INSERT", handler)

    def test_the_error_messages_are_not_in_the_script_text(self):
        # They are read from SQL Server when the script runs.
        sql = one([self.TRACK])
        self.assertIn("ERROR_MESSAGE()", sql)

    def test_a_create_that_conflicted_is_remembered(self):
        e = entry(1, "create", "TrackT", 1588, {"TrackID": {"old": None, "new": 1588},
                                               "TrackFileName": {"old": None, "new": "a.csv"}})
        sql = one([e])
        # In the conflict branch, and in the handler if the insert itself failed.
        self.assertEqual(sql.count("INSERT INTO #Skipped (TableName, RecordID) VALUES (N'TrackT', N'1588');"), 2)

    def test_what_follows_a_create_asks_whether_it_was_skipped(self):
        sql = one([self.TRACK,
                   update(2, "TrackT", 1588, "EffortID", None, 5, action="associate"),
                   update(3, "TrackT", 1588, "Vessel", None, "ROB"),
                   entry(4, "delete", "TrackT", 1588, snapshot={"TrackT": [{"TrackID": 1588, "TrackFileName": "a.csv"}]})])
        later = sql.split("-- Entry 2,")[1]
        self.assertEqual(later.count("IF EXISTS (SELECT 1 FROM #Skipped WHERE TableName = N'TrackT' AND RecordID = N'1588')"), 3)
        self.assertEqual(later.count("N'Skipped, Its Create Conflicted'"), 3)
        self.assertNotIn("#Skipped WHERE", sql.split("-- Entry 2,")[0])

    def test_an_entry_about_another_record_is_not_asked(self):
        sql = one([self.TRACK, update(2, "TrackT", 94, "EffortID", None, 5, action="associate"),
                   update(3, "SightingT", "9", "Depth", 1, 2, legacy_pk=11)])
        self.assertNotIn("#Skipped WHERE", sql)

    def test_the_skipped_entry_is_still_in_the_report(self):
        sql = one([self.TRACK, update(2, "TrackT", 1588, "EffortID", None, 5, action="associate")])
        self.assertIn("(2, N'Skipped, Its Create Conflicted', N'associate TrackT 1588')", sql)
        self.assertIn("Result   nvarchar(40) NOT NULL", sql)       # room for its name


class IdentityTests(SimpleTestCase):
    """SET IDENTITY_INSERT only where DB167 has an identity column to insert."""

    LIST = Schema(columns={"TrackFileList": {"FileID": "integer", "Name": "text"}}, keys={"TrackFileList": "FileID"})

    def test_it_is_asked_of_DB167_when_the_script_runs(self):
        sql = script.write([entry(1, "create", "TrackFileList", 7, {"FileID": {"old": None, "new": 7},
                                                                     "Name": {"old": None, "new": "a"}})], self.LIST, NOW)
        on = "IF OBJECTPROPERTY(OBJECT_ID(N'[dbo].[TrackFileList]'), 'TableHasIdentity') = 1 SET IDENTITY_INSERT [dbo].[TrackFileList] ON;"
        self.assertIn(on, sql)
        self.assertIn(on.replace(" ON;", " OFF;"), sql)

    def test_never_bare(self):
        sql = one([CreateTests.CREATE, RestoreTests().restore()])
        for line in sql.splitlines():
            if "SET IDENTITY_INSERT" in line:
                self.assertIn("IF OBJECTPROPERTY(OBJECT_ID(", line)

    def test_the_handler_asks_too(self):
        sql = script.write([entry(1, "create", "TrackFileList", 7, {"FileID": {"old": None, "new": 7}})], self.LIST, NOW)
        handler = sql.split("BEGIN CATCH\n")[1]
        self.assertIn("'TableHasIdentity') = 1 SET IDENTITY_INSERT [dbo].[TrackFileList] OFF;", handler)


class DoomedTransactionTests(SimpleTestCase):

    def sql(self):
        return one([update(5, "SightingT", "9", "Depth", 1, 2, legacy_pk=11)])

    def test_the_handler_stops_for_a_transaction_that_cannot_be_rolled_back_to_a_savepoint(self):
        handler = self.sql().split("BEGIN CATCH\n")[1].split("END CATCH;")[0]
        self.assertIn("IF XACT_STATE() <> 1 BEGIN SET @FailedEntry = 5; SET @FailedWhat = N'update SightingT 11'; GOTO Doomed; END", handler)
        self.assertNotIn("THROW", handler)

    def test_it_rolls_everything_back_prints_what_it_had_and_says_which_entry(self):
        sql = self.sql()
        doomed = sql.split("\nDoomed:\n")[1]
        self.assertIn("INSERT INTO @Saved (EntryID, Result, Detail) SELECT EntryID, Result, Detail FROM #Report WHERE EntryID <> @FailedEntry", doomed)
        self.assertLess(doomed.index("@Saved (EntryID"), doomed.index("ROLLBACK TRANSACTION;"))
        self.assertLess(doomed.index("ROLLBACK TRANSACTION;"), doomed.index("FROM @Saved ORDER BY Seq"))
        self.assertIn("NOTHING WAS COMMITTED", doomed)
        self.assertIn("the list can be empty", doomed)
        self.assertNotIn("listed above were rolled back", doomed)
        self.assertLess(doomed.index("Every entry below was rolled back"), doomed.index("FROM @Saved ORDER BY Seq"))
        self.assertIn("RAISERROR(N'%s', 16, 1, @Why);", doomed)
        self.assertTrue(doomed.rstrip().endswith("RETURN;"))
        self.assertNotIn("COMMIT;", doomed)

    def test_the_normal_end_returns_before_it(self):
        sql = self.sql()
        self.assertLess(sql.index("IF XACT_STATE() = 1 COMMIT;\nRETURN;"), sql.index("\nDoomed:\n"))

    def test_the_report_survives_a_rollback_because_it_is_a_table_variable(self):
        self.assertIn("DECLARE @Saved TABLE (", self.sql())

    def test_the_header_says_what_happens(self):
        head = self.sql().split("SET ANSI_NULLS")[0]
        self.assertIn("NOTHING IS COMMITTED in that case", head)
        self.assertIn("naming the entry", head)


class SupersededTests(SimpleTestCase):

    def track(self, number, pk=1588, file="a.csv"):
        return entry(number, "create", "TrackT", pk, {"TrackID": {"old": None, "new": pk},
                                                      "TrackFileName": {"old": None, "new": file}})

    def delete(self, number, pk=1588):
        return entry(number, "delete", "TrackT", pk, snapshot={"TrackT": [{"TrackID": pk, "TrackFileName": "a.csv"}]})

    def test_the_last_change_of_a_field_also_starts_from_the_values_it_overrides_pass_through(self):
        sql = one([update(1, "DailyEffortT", "9", "Locality", "A", "B", legacy_pk=5),
                   update(2, "DailyEffortT", "9", "Locality", "A", "C", legacy_pk=5)])
        where = sql.split("-- Entry 2")[1].split("WHERE")[1].split("AND NOT")[0]
        self.assertIn("= N'A'", where)
        self.assertIn("= N'B'", where)     # DB167 may hold the middle value

    def test_a_create_and_a_delete_are_never_superseded_whatever_follows_them(self):
        sql = one([self.track(1), self.delete(2), self.track(3, file="b.csv")])
        self.assertEqual(sql.count("INSERT INTO [dbo].[TrackT]"), 2)       # both creates, in order
        self.assertEqual(sql.count("DELETE FROM [dbo].[TrackT]"), 1)
        self.assertNotIn("Superseded", sql.split("CREATE TABLE #Skipped")[1])
        self.assertLess(sql.index("-- Entry 2,"), sql.index("-- Entry 3,"))

    def test_a_delete_then_a_create_of_the_same_track_with_a_different_file_keeps_both(self):
        # If the create conflicts, the delete has still been done and said so.
        sql = one([self.delete(1), self.track(2, file="other.csv")])
        first, second = sql.split("-- Entry 2,")
        self.assertIn("DELETE FROM [dbo].[TrackT] WHERE [TrackID] = 1588", first)
        self.assertIn("(1, N'Applied'", first)
        self.assertIn("INSERT INTO [dbo].[TrackT] ([TrackID]", second)
        self.assertIn("N'other.csv'", second)
        self.assertIn("DB167 already uses this TrackID for a different TrackFileName", second)
        self.assertNotIn("Superseded", sql.split("CREATE TABLE #Skipped")[1])

    def test_a_change_is_superseded_only_when_the_very_next_entry_about_the_record_changes_the_same_field(self):
        sql = one([update(1, "TrackT", 1588, "Vessel", "x", "z"), self.delete(2),
                   entry(3, "restore", "TrackT", 1588, snapshot={"TrackT": [{"TrackID": 1588, "Vessel": "z"}]}),
                   update(4, "TrackT", 1588, "Vessel", "z", "w")])
        # Entry 1 is written, so the delete (which checks the row as the website kept it) finds it as it should.
        self.assertIn("UPDATE [dbo].[TrackT] SET [Vessel] = N'z'", sql.split("-- Entry 2,")[0])
        self.assertNotIn("Superseded", sql.split("CREATE TABLE #Skipped")[1])
        # Entry 4 starts from z alone.
        where = sql.split("-- Entry 4,")[1].split("WHERE")[1].split("AND NOT")[0]
        self.assertIn("= N'z'", where)
        self.assertNotIn("= N'x'", where)

    def test_another_field_in_between_means_it_is_written(self):
        sql = one([update(1, "TrackT", 94, "EffortID", None, 5, action="associate"),
                   update(2, "TrackT", 94, "Vessel", None, "ROB"),
                   update(3, "TrackT", 94, "EffortID", 5, None, action="dissociate")])
        self.assertNotIn("Superseded", sql.split("CREATE TABLE #Skipped")[1])
        self.assertEqual(sql.count("UPDATE [dbo].[TrackT]"), 3)

    def test_a_run_of_changes_writes_only_the_last_and_it_starts_from_each_of_them(self):
        sql = one([update(1, "DailyEffortT", "9", "Locality", "A", "B", legacy_pk=5),
                   update(2, "DailyEffortT", "9", "Locality", "B", "C", legacy_pk=5),
                   update(3, "DailyEffortT", "9", "Locality", "C", "D", legacy_pk=5)])
        self.assertEqual(sql.count("UPDATE [dbo]"), 1)
        self.assertEqual([r for _, r in results(sql) if r == "Superseded"], ["Superseded", "Superseded"])
        where = sql.split("-- Entry 3,")[1].split("WHERE")[1].split("AND NOT")[0]
        for value in "ABC":
            self.assertIn(f"= N'{value}'", where)

    def test_the_report_says_it_was_not_written_and_what_follows_if_the_later_one_is_skipped(self):
        sql = one([update(1, "DailyEffortT", "9", "Locality", "A", "B", legacy_pk=5),
                   update(2, "DailyEffortT", "9", "Locality", "B", "C", legacy_pk=5)])
        line = [l for l in sql.splitlines() if "N'Superseded'" in l][0]
        self.assertIn("NOT WRITTEN, because entry 2 changes it again straight after", line)
        self.assertIn("If entry 2 is skipped, this one is not applied either", line)

    def test_another_record_does_not_supersede(self):
        sql = one([update(1, "TrackT", 1588, "Vessel", "x", "z"), update(2, "TrackT", 1589, "Vessel", "z", "w")])
        self.assertNotIn("Superseded", sql.split("CREATE TABLE #Skipped")[1])

    def test_it_is_in_the_header_and_says_plainly_it_is_not_written(self):
        head = one([]).split("SET ANSI_NULLS")[0]
        self.assertIn("Superseded         NOT WRITTEN", head)
        self.assertIn("If", head.split("Superseded")[1])
        self.assertIn("earlier one is not applied either", head)
