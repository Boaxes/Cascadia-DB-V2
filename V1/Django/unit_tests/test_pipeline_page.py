"""The Data Pipeline page's text, and the seed files it describes (ETL/dbt/seeds)."""

import csv
import re
from pathlib import Path

from django.test import SimpleTestCase

from datahealth import pipeline

SEEDS = Path(pipeline.__file__).resolve().parents[2] / "ETL" / "dbt" / "seeds"


def every_sentence():
    for rule in pipeline.RULES:
        yield rule["title"]
        yield from rule["text"]
        if rule["example"]:
            yield rule["example"]
    for entry in pipeline.ENTRIES:
        yield entry.get("pk_note", "")
        yield from entry.get("extra", [])


class PageTextTests(SimpleTestCase):
    def test_no_em_dashes_or_arrows(self):
        for text in every_sentence():
            self.assertNotRegex(text, "[\u2014\u2192\u2190\u21d2]", text[:60])

    def test_nothing_describes_the_old_import_entries(self):
        for text in every_sentence():
            self.assertNotIn("legacy-cleanup", text)
            self.assertNotIn("Data pipeline", text)

    def test_the_audit_log_is_said_to_hold_only_what_people_changed(self):
        edits = next(r for r in pipeline.RULES if r["title"].startswith("Edits Made on the Website"))
        self.assertIn("holds only changes people made on the website", " ".join(edits["text"]))

    def test_rules_are_referred_to_by_their_number(self):
        titles = [r["title"] for r in pipeline.RULES]
        self.assertTrue(titles[10].startswith("Corrections to Single Records"))
        self.assertTrue(titles[11].startswith("Tracks with No Vessel"))
        self.assertTrue(titles[12].startswith("A Track Follows the Effort"))
        mentioned = {int(n) for text in every_sentence() for n in re.findall(r"\brules? (\d+)\b", text)}
        self.assertLessEqual(mentioned, set(range(1, len(titles) + 1)))

    def test_the_spelling_merges_are_listed_on_their_columns(self):
        merges = {(f["table"], f["column"], f["from"]): f["to"] for f in pipeline.FIXES
                  if f["kind"] in ("typo", "synonym", "corrected", "capitals", "spaces")}
        self.assertEqual(merges[("DailyEffortT", "Locality", "Pt. St.George")], "Pt St George")
        self.assertEqual(merges[("DailyEffortT", "Locality", "N Cordell Bank")], "N. Cordell Bank")
        self.assertEqual(merges[("SampleT", "Sample Type", "Sample-Other")], "Other")
        self.assertEqual(merges[("SampleT", "Sample Type", "Skin Only")], "Skin Only Biopsy")


class SeedTests(SimpleTestCase):
    """What the page says about the single-record corrections is what the seed holds."""

    def seed(self, name):
        path = SEEDS / f"{name}.csv"
        if not path.exists():
            self.skipTest("ETL/ is not in this checkout (the web container mounts Django/ only)")
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def test_the_eleven_alaska_efforts_are_the_ones_the_page_names(self):
        ids = sorted(int(f["legacy_id"]) for f in self.seed("record_fixes") if f["rule"] == "GEO-F01")
        self.assertEqual(len(ids), 11)
        corrections = next(r for r in pipeline.RULES if r["title"].startswith("Corrections to Single Records"))
        named = re.search(r"Legacy IDs ([\d, ]+) and (\d+)\.", " ".join(corrections["text"]))
        self.assertEqual(sorted([int(n) for n in re.findall(r"\d+", named.group(1))] + [int(named.group(2))]), ids)

    def test_every_correction_names_its_record_and_changes_something(self):
        seen = set()
        for f in self.seed("record_fixes"):
            key = (f["table_name"], f["legacy_id"], f["record_date"], f["column_name"])
            self.assertNotIn(key, seen)
            seen.add(key)
            self.assertRegex(f["record_date"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertNotEqual(f["old_value"], f["new_value"])
            self.assertTrue(f["rule"] and f["reason"])
            self.assertNotRegex(f["reason"], "[\u2014\u2192]")

    def test_the_removed_effort_is_the_one_the_page_names(self):
        rows = self.seed("removed_efforts")
        self.assertEqual([(r["removed_effort"], r["kept_effort"]) for r in rows], [("10015", "10016")])
        rule = next(r for r in pipeline.RULES if r["title"].startswith("A Track Follows the Effort"))
        self.assertIn("effort 10015", rule["example"])
        self.assertIn("effort 10016", rule["example"])

    def test_the_locality_and_sample_type_spellings_are_in_the_typo_list(self):
        typos = {(t["table_name"], t["column_name"], t["wrong"]): t["correct"] for t in self.seed("typos")}
        self.assertEqual(typos[("DailyEffortT", "Locality", "Everett, N Puget Sound")], "Everett/N. Puget Sound")
        self.assertEqual(typos[("DailyEffortT", "Locality", "Pt. St. George")], "Pt St George")
        self.assertEqual(typos[("SampleT", "Sample Type", "Skin")], "Skin Only Biopsy")


class UnmatchedTracksTests(SimpleTestCase):
    """The tracks that name a removed Effort, as the page lists them."""

    class Cursor:
        def __init__(self, rows):
            self.rows = rows

        def execute(self, sql):
            self.sql = sql

        def fetchall(self):
            return self.rows

    def test_they_are_grouped_by_reason_group_and_year_with_their_ids_in_ranges(self):
        cursor = self.Cursor([(1336, "CRC", 2015, 13592), (7, "CRC", 2015, 13592), (8, "CRC", 2015, 13592),
                              (9, "CRC", 2015, 13592), (100, "CRC", 2016, 13592), (50, "PS", 2015, 99)])
        rows = pipeline.unmatched_tracks(cursor)
        self.assertEqual([(r["group"], r["year"], r["records"], r["ids"]) for r in rows],
                         [("CRC", 2015, 4, "7 to 9, 1336"), ("CRC", 2016, 1, "100"), ("PS", 2015, 1, "50")])
        self.assertEqual(rows[0]["reason"],
                         "Its effort (13592) was removed from DB167; left unmatched, waiting to be matched")
        self.assertIn("daily_effort_id IS NULL", cursor.sql)

    def test_none_is_none(self):
        self.assertEqual(pipeline.unmatched_tracks(self.Cursor([])), [])

    def test_the_file_no_longer_holds_tracks(self):
        self.assertNotIn("TrackT", pipeline.UNLINKED)
