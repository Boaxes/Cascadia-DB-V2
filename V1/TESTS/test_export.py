"""The Export Tool, against a copy of the real data.

Each expected number is worked out with plain SQL written apart from the
export code, so a mistake in one is not repeated in the other. The writers
themselves, with no database, are tested in Django/unit_tests/test_export.py.
"""

import csv
import datetime
import io
import json
import os
import re
import sqlite3
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from unittest import mock

from django.db import connection
from django.db.models import Count
from django.test import TestCase

from survey import export_sheets, export_stack, track_objects, views
from survey.export_sheets import SHEETS, Plan
from survey.models import DailyEffort, Sighting, Track
from TESTS.test_permissions import sign_in

try:
    import pyogrio
except ImportError:   # an image built before pyogrio joined requirements-dev.txt
    pyogrio = None

# Two queries that overlap: July to September Efforts, and July and August on Explore.
EFFORTS_QUERY = "year=2024&month=7&month=8&month=9"
EXPLORE_QUERY = "year=2024&month=7&month=8"

ALL_SHEETS = ["efforts", "sightings", "timeline", "weather", "samples", "identifications", "tags",
              "sighting_events", "other_species"]


def rows(sql, params=()):
    with connection.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def column(sql, params=()):
    return [r[0] for r in rows(sql, params)]


def crc_efforts(months):
    """Legacy IDs of CRC's 2024 Efforts in these months."""
    return set(column("""SELECT legacy_daily_effort_id FROM app.daily_effort
                         WHERE research_group = 'CRC' AND extract(year FROM effort_date) = 2024
                           AND extract(month FROM effort_date) = ANY(%s)""", [months]))


def crc_sightings(months):
    return set(column("""SELECT s.legacy_sighting_id FROM app.sighting s
                         LEFT JOIN app.species sp ON sp.id = s.species_id
                         WHERE s.research_group = 'CRC' AND extract(year FROM s.sighting_date) = 2024
                           AND extract(month FROM s.sighting_date) = ANY(%s)
                           AND (sp.category IS NULL OR sp.category <> 'non_animal')""", [months]))


def body(response):
    return b"".join(response.streaming_content)


def csv_rows(archive, name):
    """(headings, rows as dictionaries) of one CSV file in a zip."""
    reader = csv.reader(io.StringIO(archive.read(name).decode("utf-8-sig")))
    headings = next(reader)
    return headings, [dict(zip(headings, row)) for row in reader]


class ExportTest(TestCase):

    def setUp(self):
        sign_in(self.client, "manager", "Data Manager")

    def add(self, kind, qs="", related="0", **extra):
        """Add a query. Most tests are about the query alone, so the related
        records are off unless the test asks for them."""
        return self.client.post("/export/add/", {"kind": kind, "qs": qs, "related": related, **extra},
                                HTTP_X_REQUESTED_WITH="fetch")

    def stack(self, *queries, related="0"):
        for kind, qs in queries:
            self.assertEqual(self.add(kind, qs, related).status_code, 200)

    def plan(self):
        """The stack as the session holds it, made into the SQL that fills the sheets."""
        return Plan(self.client.session[export_stack.KEY])

    def overlapping(self):
        self.stack(("efforts", EFFORTS_QUERY), ("explore", EXPLORE_QUERY))

    def download(self, fmt="csv", sheets=("efforts", "sightings"), **params):
        response = self.client.get("/export/download/", {"format": fmt, "sheet": list(sheets), **params})
        self.assertEqual(response.status_code, 200, response.get("Location"))
        return response

    def archive(self, sheets=("efforts", "sightings"), **params):
        return zipfile.ZipFile(io.BytesIO(body(self.download("csv", sheets, **params))))


class StackTests(ExportTest):

    def test_the_stack_holds_filters_not_rows(self):
        self.stack(("efforts", EFFORTS_QUERY))
        stored = self.client.session[export_stack.KEY]
        self.assertEqual(len(stored), 1)
        self.assertEqual(set(stored[0]), {"kind", "qs", "label", "related"})
        self.assertEqual(stored[0]["kind"], "efforts")
        self.assertEqual(stored[0]["qs"], EFFORTS_QUERY)
        self.assertEqual(stored[0]["label"], "Efforts: CRC, 2024, Jul to Sep")
        self.assertLess(len(json.dumps(stored)), 400)

    def test_every_kind_can_be_added(self):
        effort = DailyEffort.objects.filter(research_group="CRC").first()
        sighting = Sighting.objects.filter(research_group="CRC").first()
        self.stack(("explore", "year=2024"), ("efforts", "year=2024"), ("sightings", "year=2024"))
        self.assertEqual(self.add("effort", id=effort.legacy_daily_effort_id).json()["label"],
                         f"Effort {effort.legacy_daily_effort_id}")
        self.assertEqual(self.add("sighting", id=sighting.legacy_sighting_id).json()["count"], 5)
        kinds = [e["kind"] for e in self.client.session[export_stack.KEY]]
        self.assertEqual(kinds, ["explore", "efforts", "sightings", "effort", "sighting"])

    def test_what_a_page_was_showing_is_not_a_filter(self):
        self.add("efforts", "year=2024&page=3&per_page=100&sort=-date&open=general&view=5,5,4")
        self.assertEqual(self.client.session[export_stack.KEY][0]["qs"], "year=2024")

    def test_repeated_values_are_all_kept(self):
        self.add("sightings", "month=7&month=8&species=1&species=2")
        self.assertEqual(self.client.session[export_stack.KEY][0]["qs"],
                         "month=7&month=8&species=1&species=2")

    def test_the_same_query_is_added_once(self):
        self.assertTrue(self.add("efforts", EFFORTS_QUERY).json()["added"])
        again = self.add("efforts", EFFORTS_QUERY).json()
        self.assertFalse(again["added"])
        self.assertEqual(again["count"], 1)

    def test_the_bar_says_how_many_queries_wait(self):
        self.assertIn(">Export<", self.client.get("/explore/").content.decode())
        self.overlapping()
        self.assertIn(">Export (2)<", self.client.get("/explore/").content.decode())

    def test_a_query_is_removed_from_the_page(self):
        self.overlapping()
        self.client.post("/export/remove/", {"index": "0"})
        stack = self.client.session[export_stack.KEY]
        self.assertEqual([e["kind"] for e in stack], ["explore"])
        self.client.post("/export/remove/", {"index": "7"})   # nothing there: nothing happens
        self.assertEqual(len(self.client.session[export_stack.KEY]), 1)

    def test_removing_without_a_script_goes_back_to_the_page_with_its_choices(self):
        self.overlapping()
        response = self.client.post("/export/remove/", {"index": "0", "next": "/export/?format=csv&tz=Pacific"})
        self.assertRedirects(response, "/export/?format=csv&tz=Pacific", fetch_redirect_response=False)
        # And never to another site.
        response = self.client.post("/export/remove/", {"index": "0", "next": "https://example.com/"})
        self.assertRedirects(response, "/export/", fetch_redirect_response=False)

    def test_a_query_that_cannot_be_read_is_refused_when_it_is_added(self):
        response = self.add("efforts", "area=not-a-shape")
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())
        self.assertEqual(self.client.session.get(export_stack.KEY, []), [])

    def test_a_record_that_is_not_there_is_refused(self):
        self.assertEqual(self.add("effort", id="0").status_code, 400)
        self.assertEqual(self.add("sighting", id="x").status_code, 400)

    def test_an_export_holds_a_limited_number_of_queries(self):
        for year in range(2000, 2000 + export_stack.MAX_QUERIES):
            self.assertEqual(self.add("efforts", f"year={year}").status_code, 200)
        response = self.add("efforts", "year=1999")
        self.assertEqual(response.status_code, 400)
        self.assertIn("at most", response.json()["error"])

    def test_one_record_is_that_record_whatever_the_research_group(self):
        other = Sighting.objects.exclude(research_group="CRC").exclude(research_group__isnull=True).first()
        self.add("sighting", id=other.legacy_sighting_id)
        plan = self.plan()
        self.assertEqual(export_sheets.BY_KEY["sightings"].count(plan), 1)

    def test_adding_without_a_script_comes_back_with_a_message(self):
        response = self.client.post("/export/add/", {"kind": "efforts", "qs": "year=2024", "next": "/export/"},
                                    follow=True)
        self.assertRedirects(response, "/export/")
        self.assertContains(response, "Added to the export: Efforts: CRC, 2024.")
        self.assertContains(response, ">Export (1)<")
        again = self.client.post("/export/add/", {"kind": "efforts", "qs": "year=2024", "next": "/export/"}, follow=True)
        self.assertContains(again, "Already in the export: Efforts: CRC, 2024.")

    def test_adding_needs_a_post(self):
        self.assertEqual(self.client.get("/export/add/").status_code, 405)
        self.assertEqual(self.client.get("/export/remove/").status_code, 405)


class PermissionTests(ExportTest):

    URLS = ("/export/", "/export/preview/?preview=efforts", "/export/download/?format=csv")

    def test_a_stranger_is_sent_to_sign_in(self):
        self.client.logout()
        for url in self.URLS:
            self.assertIn("/login/", self.client.get(url)["Location"], url)
        self.assertEqual(self.client.post("/export/add/", {"kind": "efforts"}).status_code, 302)

    def test_only_someone_who_may_export_gets_in(self):
        for role in ("Viewer", "Editor"):
            self.client.logout()
            sign_in(self.client, role.lower() + "x", role)
            for url in self.URLS:
                self.assertEqual(self.client.get(url).status_code, 403, (role, url))
            for url in ("/export/add/", "/export/remove/"):
                self.assertEqual(self.client.post(url, {"kind": "efforts", "qs": ""}).status_code, 403, (role, url))
            self.assertNotIn(export_stack.KEY, self.client.session)

    def test_export_data_can_be_granted_alone(self):
        self.client.logout()
        sign_in(self.client, "onlyexport", "Viewer", extra=["export_data"])
        self.assertEqual(self.client.get("/export/").status_code, 200)
        self.assertEqual(self.add("efforts", "year=2024").status_code, 200)

    def test_the_buttons_are_shown_to_those_who_may_use_them(self):
        effort = DailyEffort.objects.filter(research_group="CRC").first().legacy_daily_effort_id
        sighting = Sighting.objects.filter(research_group="CRC").first().legacy_sighting_id
        pages = ["/explore/", "/efforts/", "/sightings/", f"/efforts/{effort}/", f"/sightings/{sighting}/"]
        for page in pages:
            self.assertIn("To Export<", self.client.get(page).content.decode(), page)
        self.client.logout()
        sign_in(self.client, "looker", "Viewer")
        for page in pages:
            html = self.client.get(page).content.decode()
            self.assertNotIn("To Export<", html, page)
            self.assertNotIn("export-add.js", html, page)

    def test_each_page_adds_what_it_shows(self):
        effort = DailyEffort.objects.filter(research_group="CRC").first().legacy_daily_effort_id
        sighting = Sighting.objects.filter(research_group="CRC").first().legacy_sighting_id
        explore = self.client.get("/explore/?year=2024&month=7&view=4").content.decode()
        self.assertRegex(explore, r'name="kind" value="sightings"\s*>\s*<input type="hidden" name="qs" value="year=2024&amp;month=7"')
        self.assertRegex(explore, r'name="kind" value="efforts"\s*>\s*<input type="hidden" name="qs" value="year=2024&amp;month=7"')
        lists = self.client.get("/sightings/?year=2024&page=2&sort=date").content.decode()
        self.assertRegex(lists, r'name="kind" value="sightings"\s*>\s*<input type="hidden" name="qs" value="year=2024"')
        efforts = self.client.get("/efforts/?year=2024").content.decode()
        self.assertRegex(efforts, r'name="kind" value="efforts"\s*>\s*<input type="hidden" name="qs" value="year=2024"')
        self.assertRegex(self.client.get(f"/efforts/{effort}/").content.decode(),
                         rf'name="kind" value="effort"\s*>\s*<input type="hidden" name="id" value="{effort}"')
        self.assertRegex(self.client.get(f"/sightings/{sighting}/").content.decode(),
                         rf'name="kind" value="sighting"\s*>\s*<input type="hidden" name="id" value="{sighting}"')


    def test_explore_has_a_button_for_each_tab_and_shows_sightings_first(self):
        html = self.client.get("/explore/?year=2024").content.decode()
        self.assertNotIn('value="explore"', html)
        forms = re.findall(r'<form[^>]*data-add-export[^>]*>', html)
        self.assertEqual(len(forms), 2)
        self.assertIn('data-export-tab="sightings"', forms[0])
        self.assertNotIn("hidden", forms[0])
        self.assertIn('data-export-tab="efforts"', forms[1])
        self.assertIn("hidden", forms[1])
        self.assertIn(">Add Sightings To Export<", html)
        self.assertIn(">Add Efforts To Export<", html)


class TheOldExportIsGoneTests(ExportTest):

    def test_the_old_view_and_its_helpers_are_removed(self):
        for name in ("export_page", "export_download", "remember_export_state", "export_state", "zip_with_tracks"):
            self.assertFalse(hasattr(views, name), name)
        from survey import exporters
        for name in ("columns_for", "csv_response", "excel_response", "geojson_response", "OPTIONAL_SIGHTING_FIELDS"):
            self.assertFalse(hasattr(exporters, name), name)

    def test_the_icon_that_downloaded_one_record_is_gone(self):
        sighting = Sighting.objects.filter(research_group="CRC").first().legacy_sighting_id
        html = self.client.get(f"/sightings/{sighting}/").content.decode()
        self.assertNotIn("area=sightings&amp;format=csv", html)
        self.assertNotIn('aria-label="Export"', html)

    def test_a_link_to_the_old_download_is_refused_with_a_reason_not_an_error(self):
        response = self.client.get("/export/download/?area=sightings&format=csv&tracks=1&one=1", follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add a query to the export first.")

    def test_the_old_screen_is_replaced(self):
        html = self.client.get("/export/").content.decode()
        self.assertNotIn("1. What to export", html)
        self.assertIn("Nothing to export yet.", html)


class PageTests(ExportTest):

    def test_the_page_lists_the_queries_and_their_counts(self):
        self.overlapping()
        html = self.client.get("/export/").content.decode()
        self.assertIn("Efforts: CRC, 2024, Jul to Sep", html)
        self.assertIn("Explore: CRC, 2024, Jul to Aug", html)
        response = self.client.get("/export/")
        first, second = response.context["queries"]
        self.assertEqual(first["efforts"], len(crc_efforts([7, 8, 9])))
        self.assertIsNone(first["sightings"])
        self.assertEqual(second["efforts"], len(crc_efforts([7, 8])))
        self.assertEqual(second["sightings"], len(crc_sightings([7, 8])))
        self.assertIn("Queries combine with OR", html)

    def test_the_sheets_carry_their_true_row_counts(self):
        self.overlapping()
        counts = {s["key"]: s["rows"] for s in self.client.get("/export/").context["sheets"]}
        efforts = crc_efforts([7, 8, 9])
        sightings = crc_sightings([7, 8])
        self.assertEqual(counts["efforts"], len(efforts))
        self.assertEqual(counts["sightings"], len(sightings))
        self.assertEqual(counts["timeline"], rows("""
            SELECT count(*) FROM app.effort_timeline t JOIN app.daily_effort e ON e.id = t.daily_effort_id
            WHERE t.kind <> 'sighting' AND e.legacy_daily_effort_id = ANY(%s)""", [list(efforts)])[0][0])
        self.assertEqual(counts["weather"], rows("""
            SELECT count(*) FROM app.daily_condition c JOIN app.daily_effort e ON e.id = c.daily_effort_id
            WHERE e.legacy_daily_effort_id = ANY(%s)""", [list(efforts)])[0][0])
        self.assertEqual(counts["samples"], rows("""
            SELECT count(*) FROM app.sample sm JOIN app.sighting s ON s.id = sm.sighting_id
            WHERE s.legacy_sighting_id = ANY(%s)""", [list(sightings)])[0][0])
        self.assertEqual(counts["tags"], rows("""
            SELECT count(*) FROM dbo."TagSummaryT" t JOIN app.sighting s ON s.id = t.sighting_id
            WHERE s.legacy_sighting_id = ANY(%s)""", [list(sightings)])[0][0])
        self.assertNotIn("gps_points", counts)

    def test_the_page_keeps_what_was_chosen(self):
        self.overlapping()
        response = self.client.get("/export/?format=gpkg&tz=Pacific&df=excel&raw=1&sheet=timeline"
                                   "&col_efforts=&col_efforts=date")
        choice = response.context["choice"]
        self.assertEqual((choice.format, choice.zone.name, choice.date_format, choice.raw, choice.sheets),
                         ("gpkg", "Pacific", "iso", True, ["timeline"]))   # GeoPackage is always ISO
        efforts = next(s for s in response.context["sheets"] if s["key"] == "efforts")
        self.assertEqual(efforts["chosen"], 2)   # the Effort ID that cannot be unticked, and Date

    def test_no_query_no_download(self):
        response = self.client.get("/export/")
        self.assertContains(response, 'id="dl" disabled')

    def test_the_download_is_refused_with_a_reason(self):
        response = self.client.get("/export/download/?format=csv&sheet=efforts", follow=True)
        self.assertContains(response, "Add a query to the export first.")
        self.stack(("efforts", EFFORTS_QUERY))
        response = self.client.get("/export/download/?format=csv", follow=True)
        self.assertContains(response, "Tick at least one sheet")
        response = self.client.get("/export/download/?format=pdf&sheet=efforts", follow=True)
        self.assertContains(response, "pdf is not a format")

    def test_the_preview_is_the_first_rows_and_the_true_count(self):
        self.overlapping()
        data = self.client.get("/export/preview/?preview=efforts&format=csv").json()
        self.assertEqual(len(data["rows"]), export_sheets.PREVIEW_ROWS)
        self.assertEqual(data["total"], len(crc_efforts([7, 8, 9])))
        labels = [c["label"] for c in data["columns"]]
        self.assertEqual(labels[0], "Matched Queries")
        appended = {c["label"] for c in data["columns"] if c["appended"]}
        self.assertIn("Vessel Code", appended)
        self.assertIn("Track File", appended)
        self.assertNotIn("Locality", appended)
        self.assertNotIn("Matched Queries", appended)
        self.assertEqual(self.client.get("/export/preview/?preview=nothing").status_code, 404)

    def test_the_preview_follows_the_columns_and_the_zone(self):
        self.stack(("efforts", EFFORTS_QUERY))
        data = self.client.get("/export/preview/?preview=efforts&format=csv&col_efforts=&col_efforts=date").json()
        self.assertEqual([c["label"] for c in data["columns"]], ["Effort ID", "Date"])
        self.assertTrue(all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", r[1]) for r in data["rows"]))
        excel = self.client.get("/export/preview/?preview=efforts&format=csv&df=excel&col_efforts=&col_efforts=date").json()
        self.assertTrue(all(re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", r[1]) for r in excel["rows"]))


class AppendedColumnTests(ExportTest):

    def test_related_values_with_one_row_per_parent_are_columns(self):
        self.overlapping()
        archive = self.archive()
        # Nothing but the two sheets: no file for Vessels, Species or Tracks.
        self.assertEqual(sorted(archive.namelist()), ["efforts.csv", "sightings.csv"])
        efforts, _ = csv_rows(archive, "efforts.csv")
        for heading in ("Vessel Code", "Vessel Name", "Track File", "Track Points", "Track Length (nm)"):
            self.assertIn(heading, efforts)
        sightings, _ = csv_rows(archive, "sightings.csv")
        for heading in ("Species Code", "Common Name", "Scientific Name", "Vessel Code",
                        "Effort Date", "Effort Locality", "Track File"):
            self.assertIn(heading, sightings)

    def test_every_column_can_be_chosen(self):
        self.stack(("efforts", EFFORTS_QUERY), ("sightings", EXPLORE_QUERY))
        every = {sheet.key: [c.key for c in sheet.columns] for sheet in SHEETS if sheet.chooser}
        archive = self.archive(("efforts", "sightings"),
                               **{f"col_{key}": ["", *keys] for key, keys in every.items()})
        efforts, _ = csv_rows(archive, "efforts.csv")
        self.assertEqual(efforts[1:] if efforts[0] == "Matched Queries" else efforts,
                         [c.label for c in export_sheets.BY_KEY["efforts"].columns])
        sightings, _ = csv_rows(archive, "sightings.csv")
        self.assertEqual([h for h in sightings if h != "Matched Queries"],
                         [c.label for c in export_sheets.BY_KEY["sightings"].columns])

    def test_unticked_columns_are_left_out_and_the_id_stays(self):
        self.stack(("efforts", EFFORTS_QUERY))
        archive = self.archive(("efforts",), col_efforts=["", "locality", "vessel_code"])
        headings, _ = csv_rows(archive, "efforts.csv")
        self.assertEqual(headings, ["Effort ID", "Locality", "Vessel Code"])

    def test_the_default_columns(self):
        self.stack(("efforts", EFFORTS_QUERY))
        headings, _ = csv_rows(self.archive(("efforts",)), "efforts.csv")
        self.assertEqual(headings, ["Effort ID", "Date", "Locality", "Region", "Survey Type", "Research Group",
                                    "Vessel Code", "Vessel Name", "Track File", "Track Points", "Track Length (nm)"])

    def test_effort_values_come_from_the_effort_its_vessel_and_its_track(self):
        self.stack(("efforts", EFFORTS_QUERY))
        _, data = csv_rows(self.archive(("efforts",)), "efforts.csv")
        by_id = {int(r["Effort ID"]): r for r in data}
        self.assertEqual(set(by_id), crc_efforts([7, 8, 9]))
        for legacy_id, vessel, locality, file_name, points in rows("""
                SELECT e.legacy_daily_effort_id, v.code, e.locality, t.file_name, t.point_count
                FROM app.daily_effort e LEFT JOIN app.vessel v ON v.id = e.vessel_id
                LEFT JOIN LATERAL (SELECT file_name, point_count FROM dbo."TrackT" x
                                   WHERE x.daily_effort_id = e.id ORDER BY x."TrackID" LIMIT 1) t ON true
                WHERE e.legacy_daily_effort_id = ANY(%s)""", [list(by_id)]):
            row = by_id[legacy_id]
            self.assertEqual(row["Vessel Code"], vessel or "", legacy_id)
            self.assertEqual(row["Locality"], locality or "", legacy_id)
            self.assertEqual(row["Track File"], file_name or "", legacy_id)
            self.assertEqual(row["Track Points"], "" if points is None else str(points), legacy_id)

    def test_an_effort_with_several_tracks_carries_the_first_by_track_id(self):
        legacy_id = column("""
            SELECT e.legacy_daily_effort_id FROM app.daily_effort e
            WHERE e.id IN (SELECT daily_effort_id FROM dbo."TrackT" GROUP BY 1
                           HAVING count(*) > 1 AND count(DISTINCT file_name) > 1)
            ORDER BY 1 LIMIT 1""")[0]
        self.add("effort", id=legacy_id)
        first = rows("""SELECT file_name, point_count FROM dbo."TrackT"
                        WHERE daily_effort_id = (SELECT id FROM app.daily_effort WHERE legacy_daily_effort_id = %s)
                        ORDER BY "TrackID" LIMIT 1""", [legacy_id])[0]
        _, data = csv_rows(self.archive(("efforts",)), "efforts.csv")
        self.assertEqual(len(data), 1)    # one row for the Effort, not one for each track
        self.assertEqual((data[0]["Track File"], data[0]["Track Points"]), (first[0], str(first[1])))

    def test_sighting_values_come_from_the_sighting_its_species_vessel_and_effort(self):
        self.stack(("sightings", EXPLORE_QUERY))
        _, data = csv_rows(self.archive(("sightings",)), "sightings.csv")
        by_id = {int(r["Sighting ID"]): r for r in data}
        self.assertEqual(set(by_id), crc_sightings([7, 8]))
        for legacy_id, species, scientific, vessel, effort, effort_date, locality in rows("""
                SELECT s.legacy_sighting_id, sp.code, sp.scientific_name, v.code,
                       e.legacy_daily_effort_id, e.effort_date, e.locality
                FROM app.sighting s LEFT JOIN app.species sp ON sp.id = s.species_id
                LEFT JOIN app.vessel v ON v.id = s.vessel_id
                LEFT JOIN app.daily_effort e ON e.id = s.daily_effort_id
                WHERE s.legacy_sighting_id = ANY(%s)""", [list(by_id)]):
            row = by_id[legacy_id]
            self.assertEqual(row["Species Code"], species or "", legacy_id)
            self.assertEqual(row["Scientific Name"], scientific or "", legacy_id)
            self.assertEqual(row["Vessel Code"], vessel or "", legacy_id)
            self.assertEqual(row["Effort ID"], "" if effort is None else str(effort), legacy_id)
            self.assertEqual(row["Effort Locality"], locality or "", legacy_id)

    def test_only_what_the_site_shows_is_exported(self):
        # DB167's own bearing, range and reticle readings are not on any page.
        every = [c.label for sheet in SHEETS for c in sheet.columns]
        for hidden in ("Bearing", "Range To The Group", "Reticle", "Photographer", "Photo Series"):
            self.assertNotIn(hidden, every)


class OnlyManyPerParentGetASheetTests(ExportTest):

    def test_the_sheets_are_exactly_the_listed_ones(self):
        self.assertEqual([s.key for s in SHEETS], ALL_SHEETS)
        self.assertEqual([s.title for s in SHEETS],
                         ["Efforts", "Sightings", "Timeline", "Weather", "Samples", "Identifications", "Tags",
                          "Sighting Events", "Other Species"])

    def test_there_is_no_gps_points_sheet_anywhere(self):
        self.assertNotIn("GPS Points", self.client.get("/export/").content.decode())
        self.assertEqual(self.client.get("/export/preview/?preview=gps_points").status_code, 404)
        self.assertFalse(hasattr(export_sheets, "GpsSheet"))
        self.assertFalse(hasattr(export_sheets, "GPS_COLUMNS"))

    def test_an_excel_workbook_has_one_sheet_for_each_ticked_sheet(self):
        from openpyxl import load_workbook
        self.overlapping()
        book = load_workbook(io.BytesIO(body(self.download("xlsx", ALL_SHEETS))), read_only=True)
        self.assertEqual(book.sheetnames, [s.title for s in SHEETS])
        ticked = load_workbook(io.BytesIO(body(self.download("xlsx", ["sightings", "tags"]))), read_only=True)
        self.assertEqual(ticked.sheetnames, ["Sightings", "Tags"])

    def test_each_is_keyed_by_the_id_of_its_parent(self):
        self.overlapping()
        archive = self.archive(ALL_SHEETS)
        efforts = {r["Effort ID"] for r in csv_rows(archive, "efforts.csv")[1]}
        sightings = {r["Sighting ID"] for r in csv_rows(archive, "sightings.csv")[1]}
        for name, key, parents in (("timeline", "Effort ID", efforts), ("weather", "Effort ID", efforts),
                                   ("samples", "Sighting ID", sightings), ("identifications", "Sighting ID", sightings),
                                   ("tags", "Sighting ID", sightings), ("sighting_events", "Sighting ID", sightings),
                                   ("other_species", "Sighting ID", sightings)):
            headings, data = csv_rows(archive, f"{name}.csv")
            self.assertIn(key, headings, name)
            self.assertTrue({r[key] for r in data} <= parents, name)

    def test_the_timeline_merges_conditions_and_the_day_log_by_time(self):
        self.stack(("efforts", EFFORTS_QUERY))
        headings, data = csv_rows(self.archive(("timeline",)), "timeline.csv")
        self.assertEqual(headings, ["Effort ID", "Date And Time", "Kind", "Detail", "Latitude", "Longitude"])
        self.assertEqual({r["Kind"] for r in data}, {"Weather reading", "Log entry"})
        for effort in {r["Effort ID"] for r in data}:
            times = [r["Date And Time"] for r in data if r["Effort ID"] == effort]
            self.assertEqual(times, sorted(times), effort)
        self.assertEqual(len(data), rows("""
            SELECT count(*) FROM app.effort_timeline t JOIN app.daily_effort e ON e.id = t.daily_effort_id
            WHERE t.kind <> 'sighting' AND e.legacy_daily_effort_id = ANY(%s)""", [list(crc_efforts([7, 8, 9]))])[0][0])

    def test_the_weather_sheet_has_one_row_per_reading(self):
        self.stack(("efforts", EFFORTS_QUERY))
        headings, data = csv_rows(self.archive(("weather",)), "weather.csv")
        self.assertEqual(headings, ["Effort ID", "Date And Time", "Beaufort", "Swell (ft)", "Cloud Cover (%)",
                                    "Precipitation", "Quality", "Visibility (nm)", "Comments", "Latitude", "Longitude"])
        self.assertEqual(len(data), rows("""
            SELECT count(*) FROM app.daily_condition c JOIN app.daily_effort e ON e.id = c.daily_effort_id
            WHERE e.legacy_daily_effort_id = ANY(%s)""", [list(crc_efforts([7, 8, 9]))])[0][0])
        self.assertNotIn("weather", export_sheets.DEFAULT_SHEETS)

    def test_the_weather_date_and_time_follows_the_zone(self):
        reading = rows("""SELECT e.legacy_daily_effort_id, c.condition_datetime,
                                 c.condition_datetime AT TIME ZONE 'America/Los_Angeles' AT TIME ZONE 'UTC'
                          FROM app.daily_condition c JOIN app.daily_effort e ON e.id = c.daily_effort_id
                          WHERE e.research_group = 'CRC' AND c.condition_datetime::time > '01:00'
                          ORDER BY c.id LIMIT 1""")[0]
        self.add("effort", id=reading[0])
        wanted = lambda value: value.strftime("%Y-%m-%d %H:%M:%S")
        for zone, expected in (("Pacific", reading[1]), ("UTC", reading[2])):
            _, data = csv_rows(self.archive(("weather",), tz=zone), "weather.csv")
            self.assertIn(wanted(expected), [r["Date And Time"] for r in data], zone)

    def test_the_attached_records_are_what_a_sightings_page_shows(self):
        self.stack(("sightings", EXPLORE_QUERY))
        archive = self.archive(("identifications", "tags", "sighting_events", "other_species", "samples"))
        expected = {
            "identifications": ["Sighting ID", "CRC ID", "Field ID", "Species"],
            "tags": ["Sighting ID", "Tag Number", "Tag Type", "Deploy Body Location", "Deployed",
                     "Deploy Reaction", "Hours Total", "Comments"],
            "sighting_events": ["Sighting ID", "Event Time", "Event", "Field ID", "Reaction",
                                "Number Reacting", "Range", "Comments"],
            "other_species": ["Sighting ID", "Species", "Class", "Count", "Comments"],
            "samples": ["Sighting ID", "Sample Number", "Sample Type", "Species", "Preservation", "Sampled By"],
        }
        for name, headings in expected.items():
            found, data = csv_rows(archive, f"{name}.csv")
            self.assertEqual(found, headings, name)
        # The same rows the page's own query finds for one of these sightings.
        sighting = next(r["Sighting ID"] for r in csv_rows(archive, "other_species.csv")[1])
        page = views._attached_records(Sighting.objects.get(legacy_sighting_id=sighting))
        shown = next(g for g in page if g["label"] == "Other Species Present")
        mine = [r for r in csv_rows(archive, "other_species.csv")[1] if r["Sighting ID"] == sighting]
        self.assertEqual(len(mine), len(shown["rows"]))


class StackedQueriesTests(ExportTest):

    def test_a_row_that_matches_two_queries_appears_once(self):
        self.overlapping()
        archive = self.archive()
        _, efforts = csv_rows(archive, "efforts.csv")
        _, sightings = csv_rows(archive, "sightings.csv")
        # One Efforts sheet and one Sightings sheet, the union of the queries.
        self.assertEqual({int(r["Effort ID"]) for r in efforts}, crc_efforts([7, 8, 9]) | crc_efforts([7, 8]))
        self.assertEqual(len(efforts), len(crc_efforts([7, 8, 9])))
        self.assertEqual(len({r["Effort ID"] for r in efforts}), len(efforts))
        self.assertEqual({int(r["Sighting ID"]) for r in sightings}, crc_sightings([7, 8]))
        self.assertEqual(len({r["Sighting ID"] for r in sightings}), len(sightings))

    def test_the_matched_queries_column_says_which_queries_matched(self):
        self.overlapping()
        headings, efforts = csv_rows(self.archive(("efforts",)), "efforts.csv")
        self.assertEqual(headings[0], "Matched Queries")
        both, only_first = crc_efforts([7, 8]), crc_efforts([7, 8, 9]) - crc_efforts([7, 8])
        got = {int(r["Effort ID"]): r["Matched Queries"] for r in efforts}
        self.assertTrue(both and only_first)
        for effort in both:
            self.assertEqual(got[effort], "1, 2", effort)
        for effort in only_first:
            self.assertEqual(got[effort], "1", effort)
        # The second query is Explore, and it gives Sightings; the first gives none.
        _, sightings = csv_rows(self.archive(("sightings",)), "sightings.csv")
        self.assertEqual({r["Matched Queries"] for r in sightings}, {"2"})

    def test_one_query_has_no_matched_queries_column(self):
        self.stack(("explore", EXPLORE_QUERY))
        archive = self.archive()
        for name in ("efforts.csv", "sightings.csv"):
            self.assertNotIn("Matched Queries", csv_rows(archive, name)[0])

    def test_removing_the_second_query_takes_the_column_away(self):
        self.overlapping()
        self.client.post("/export/remove/", {"index": "1"})
        self.assertNotIn("Matched Queries", csv_rows(self.archive(("efforts",)), "efforts.csv")[0])

    def test_only_the_efforts_and_sightings_sheets_have_it(self):
        self.overlapping()
        archive = self.archive(ALL_SHEETS)
        for name in ("timeline", "weather", "samples", "identifications", "tags", "sighting_events", "other_species"):
            self.assertNotIn("Matched Queries", csv_rows(archive, f"{name}.csv")[0], name)

    def test_a_query_can_be_a_single_record_beside_others(self):
        effort = DailyEffort.objects.filter(research_group="CRC", effort_date__year=2023).first()
        self.stack(("efforts", EFFORTS_QUERY))
        self.add("effort", id=effort.legacy_daily_effort_id)
        _, data = csv_rows(self.archive(("efforts",)), "efforts.csv")
        got = {int(r["Effort ID"]): r["Matched Queries"] for r in data}
        self.assertEqual(got[effort.legacy_daily_effort_id], "2")
        self.assertEqual(len(got), len(crc_efforts([7, 8, 9])) + 1)

    def test_the_filters_are_the_sites_own(self):
        """Research Group (CRC unless chosen), Sub-Area, Tags and Samples reach
        the export through filters.py, the same as the lists."""
        every = len(set(column("SELECT legacy_daily_effort_id FROM app.daily_effort")))
        self.stack(("efforts", "research_group=all"))
        self.assertEqual(export_sheets.BY_KEY["efforts"].count(self.plan()), every)
        self.client.post("/export/remove/", {"index": "0"})
        self.stack(("efforts", "year=2024&tags=with"))
        with_tags = set(column("""
            SELECT DISTINCT e.legacy_daily_effort_id FROM app.daily_effort e
            WHERE e.research_group = 'CRC' AND extract(year FROM e.effort_date) = 2024 AND (
              EXISTS (SELECT 1 FROM dbo."TagSummaryT" t WHERE t.daily_effort_id = e.id)
              OR EXISTS (SELECT 1 FROM dbo."TagSummaryT" t JOIN dbo."SightingT" s ON s.id = t.sighting_id
                         WHERE s.daily_effort_id = e.id))"""))
        _, data = csv_rows(self.archive(("efforts",)), "efforts.csv")
        self.assertEqual({int(r["Effort ID"]) for r in data}, with_tags)

    def test_the_download_reads_the_database_as_it_is_now(self):
        self.stack(("efforts", EFFORTS_QUERY))
        effort = sorted(crc_efforts([7, 8, 9]))[0]
        before = {int(r["Effort ID"]): r["Locality"] for r in csv_rows(self.archive(("efforts",)), "efforts.csv")[1]}
        with connection.cursor() as cur:
            cur.execute("UPDATE app.daily_effort SET locality = 'Changed After It Was Added' "
                        "WHERE legacy_daily_effort_id = %s", [effort])
        after = {int(r["Effort ID"]): r["Locality"] for r in csv_rows(self.archive(("efforts",)), "efforts.csv")[1]}
        self.assertNotEqual(before[effort], "Changed After It Was Added")
        self.assertEqual(after[effort], "Changed After It Was Added")


class FormatTests(ExportTest):

    def setUp(self):
        super().setUp()
        self.overlapping()

    def test_excel(self):
        from openpyxl import load_workbook
        response = self.download("xlsx", ["efforts", "sightings", "timeline"])
        self.assertEqual(response["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertRegex(response["Content-Disposition"], r'attachment; filename="cascadia_export_\d{4}-\d{2}-\d{2}_utc\.xlsx"')
        book = load_workbook(io.BytesIO(body(response)))
        sheet = book["Efforts"]
        self.assertEqual(sheet.max_row - 1, len(crc_efforts([7, 8, 9])))
        self.assertEqual(sheet["A1"].value, "Matched Queries")
        self.assertIsInstance(sheet["C2"].value, datetime.datetime)   # a real date, not text
        self.assertEqual(sheet.freeze_panes, "A2")

    def test_csv(self):
        response = self.download("csv", ["efforts", "sightings"])
        self.assertEqual(response["Content-Type"], "application/zip")
        archive = zipfile.ZipFile(io.BytesIO(body(response)))
        self.assertEqual(sorted(archive.namelist()), ["efforts.csv", "sightings.csv"])
        self.assertTrue(archive.read("efforts.csv").startswith(b"\xef\xbb\xbf"))

    def test_geojson(self):
        archive = zipfile.ZipFile(io.BytesIO(body(self.download("geojson", ["efforts", "sightings", "samples"]))))
        self.assertEqual(sorted(archive.namelist()), ["efforts.geojson", "sightings.geojson"])
        efforts = json.loads(archive.read("efforts.geojson"))
        self.assertEqual(len(efforts["features"]), len(crc_efforts([7, 8, 9])))
        lines = [f for f in efforts["features"] if f["geometry"]]
        self.assertTrue(lines)
        self.assertEqual({f["geometry"]["type"] for f in lines}, {"MultiLineString"})
        sightings = json.loads(archive.read("sightings.geojson"))
        self.assertEqual(len(sightings["features"]), len(crc_sightings([7, 8])))
        feature = next(f for f in sightings["features"] if f["geometry"])
        lon, lat = rows("SELECT lon, lat FROM app.sighting WHERE legacy_sighting_id = %s",
                        [feature["properties"]["Sighting ID"]])[0]
        self.assertEqual(feature["geometry"]["coordinates"], [float(lon), float(lat)])
        self.assertIn("Common Name", feature["properties"])

    def test_geojson_holds_a_weather_layer_with_a_feature_for_each_reading(self):
        self.stack(("efforts", EFFORTS_QUERY))
        archive = zipfile.ZipFile(io.BytesIO(body(self.download("geojson", ["weather"]))))
        self.assertEqual(archive.namelist(), ["weather.geojson"])
        features = json.loads(archive.read("weather.geojson"))["features"]
        self.assertEqual(len(features), rows("""
            SELECT count(*) FROM app.daily_condition c JOIN app.daily_effort e ON e.id = c.daily_effort_id
            WHERE e.legacy_daily_effort_id = ANY(%s)""", [list(crc_efforts([7, 8, 9]))])[0][0])
        self.assertEqual({f["geometry"]["type"] for f in features if f["geometry"]}, {"Point"})

    def test_gpx(self):
        response = self.download("gpx", ["efforts", "sightings", "samples"])
        self.assertEqual(response["Content-Type"], "application/gpx+xml")
        ns = {"g": "http://www.topografix.com/GPX/1/1"}
        root = ET.fromstring(body(response))
        waypoints, tracks = root.findall("g:wpt", ns), root.findall("g:trk", ns)
        self.assertEqual(len(waypoints), len([s for s in crc_sightings([7, 8])
                                              if rows("SELECT geom IS NOT NULL FROM app.sighting WHERE legacy_sighting_id = %s", [s])[0][0]]))
        # An Effort's track is its first by Track ID.
        with_track = {e for e in crc_efforts([7, 8, 9]) if rows(
            """SELECT 1 FROM app.daily_effort e JOIN LATERAL (
                   SELECT geom FROM app.track x WHERE x.daily_effort_id = e.id ORDER BY x.legacy_track_id LIMIT 1) t ON true
               WHERE e.legacy_daily_effort_id = %s AND t.geom IS NOT NULL""", [e])}
        self.assertEqual(len(tracks), len(with_track))
        self.assertTrue(tracks[0].find("g:trkseg/g:trkpt", ns) is not None)

    def test_gpx_is_always_utc(self):
        sighting = rows("""SELECT s.legacy_sighting_id, s.sighting_date, s.sighting_time,
                                  ((s.sighting_date + s.sighting_time) AT TIME ZONE 'America/Los_Angeles') AT TIME ZONE 'UTC'
                           FROM app.sighting s WHERE s.research_group = 'CRC' AND s.sighting_time IS NOT NULL
                             AND s.geom IS NOT NULL ORDER BY s.id LIMIT 1""")[0]
        self.client.post("/export/remove/", {"index": "1"})
        self.client.post("/export/remove/", {"index": "0"})
        self.add("sighting", id=sighting[0])
        ns = {"g": "http://www.topografix.com/GPX/1/1"}
        root = ET.fromstring(body(self.download("gpx", ["sightings"], tz="Pacific")))
        self.assertEqual(root.find("g:wpt/g:time", ns).text, sighting[3].strftime("%Y-%m-%dT%H:%M:%SZ"))

    def test_geopackage(self):
        response = self.download("gpkg", ["efforts", "sightings", "samples"])
        self.assertEqual(response["Content-Type"], "application/geopackage+sqlite3")
        self.assertRegex(response["Content-Disposition"], r'\.gpkg"')
        handle = tempfile.NamedTemporaryFile(suffix=".gpkg", delete=False)
        handle.write(body(response))
        handle.close()
        self.addCleanup(os.unlink, handle.name)

        db = sqlite3.connect(handle.name)
        self.addCleanup(db.close)
        self.assertEqual(set(r[0] for r in db.execute("SELECT table_name FROM gpkg_contents")), {"efforts", "sightings"})
        self.assertEqual(db.execute("SELECT count(*) FROM efforts").fetchone()[0], len(crc_efforts([7, 8, 9])))

        if pyogrio is None:
            self.skipTest("pyogrio is not installed, so GDAL did not open the file")
        self.assertEqual({name for name, _kind in pyogrio.list_layers(handle.name)}, {"efforts", "sightings"})
        info = pyogrio.read_info(handle.name, layer="sightings")
        self.assertEqual(info["features"], len(crc_sightings([7, 8])))
        self.assertEqual(info["crs"], "EPSG:4326")
        _meta, _fids, geometry, _fields = pyogrio.raw.read(handle.name, layer="efforts")
        self.assertEqual(len(geometry), len(crc_efforts([7, 8, 9])))
        self.assertTrue(any(g is not None for g in geometry))

    def test_a_format_that_holds_none_of_the_ticked_sheets_says_so(self):
        for fmt, sheets, why in (("geojson", ["samples", "tags"], "have positions"),
                                 ("gpkg", ["identifications"], "have positions"),
                                 ("gpx", ["timeline"], "Efforts as tracks")):
            response = self.client.get("/export/download/", {"format": fmt, "sheet": sheets}, follow=True)
            self.assertContains(response, why)

    def test_the_downloads_are_not_compressed_again_but_the_pages_are(self):
        for fmt in ("xlsx", "csv", "gpkg", "gpx", "geojson"):
            response = self.client.get("/export/download/", {"format": fmt, "sheet": ["efforts", "sightings"]},
                                       HTTP_ACCEPT_ENCODING="gzip")
            self.assertEqual(response.status_code, 200, fmt)
            self.assertFalse(response.has_header("Content-Encoding"), fmt)
        page = self.client.get("/export/", HTTP_ACCEPT_ENCODING="gzip")
        self.assertEqual(page["Content-Encoding"], "gzip")

    def test_it_streams_from_a_file_that_goes_away_when_it_has_been_sent(self):
        response = self.download("csv")
        self.assertTrue(response.streaming)
        self.assertEqual(type(response).__name__, "FileResponse")
        self.assertIn("attachment", response["Content-Disposition"])


class FormatNoteTests(ExportTest):
    """What each format says about itself is written once, in exporters.FORMATS,
    and the page is given it, so the script cannot say something different."""

    def test_the_page_carries_each_formats_note_and_what_it_holds(self):
        html = self.client.get("/export/").content.decode()
        from django.utils.html import escape
        from survey.exporters import FORMATS
        for key, f in FORMATS.items():
            self.assertIn(f'data-note="{escape(f["note"])}"', html, key)
        self.assertIn('value="gpx" data-note="One GPX file: Efforts as tracks and Sightings as waypoints. '
                      'Efforts without a track are left out.', html)
        self.assertRegex(html, r'value="gpx"[^>]*data-holds="efforts,sightings"')
        self.assertRegex(html, r'value="geojson"[^>]*data-holds="efforts,sightings,timeline,weather"')
        self.assertRegex(html, r'value="xlsx"[^>]*data-holds="efforts,sightings,timeline,weather,samples,identifications,tags,sighting_events,other_species"')
        # Only the formats whose own file is a zip say so, which is when the raw files change nothing.
        self.assertRegex(html, r'value="csv"[^>]*data-zipped="1"')
        self.assertRegex(html, r'value="geojson"[^>]*data-zipped="1"')
        self.assertNotRegex(html, r'value="xlsx"[^>]*data-zipped')
        self.assertNotRegex(html, r'value="gpkg"[^>]*data-zipped')

    def test_the_script_holds_no_copy_of_them(self):
        from django.contrib.staticfiles import finders
        from survey.exporters import FORMATS
        script = open(finders.find("survey/export.js")).read()
        for f in FORMATS.values():
            self.assertNotIn(f["note"][:30], script)
        self.assertNotIn("gps_points", script)


class TimeZoneAndDateTests(ExportTest):

    def one_sighting(self):
        found = rows("""SELECT s.legacy_sighting_id, s.sighting_date, s.sighting_time,
                               ((s.sighting_date + s.sighting_time) AT TIME ZONE 'America/Los_Angeles') AT TIME ZONE 'UTC'
                        FROM app.sighting s WHERE s.research_group = 'CRC' AND s.sighting_time > '08:00'
                          AND s.lat IS NOT NULL AND extract(month FROM s.sighting_date) = 7 ORDER BY s.id LIMIT 1""")[0]
        self.add("sighting", id=found[0])
        return found

    def test_pacific_leaves_the_recorded_times_as_the_site_shows_them(self):
        legacy_id, day, clock, _ = self.one_sighting()
        _, data = csv_rows(self.archive(("sightings",), tz="Pacific"), "sightings.csv")
        self.assertEqual((data[0]["Date"], data[0]["Time"]), (str(day), clock.strftime("%H:%M:%S")))

    def test_utc_moves_them_by_the_hours_pacific_is_behind(self):
        legacy_id, day, clock, in_utc = self.one_sighting()
        _, data = csv_rows(self.archive(("sightings",), tz="UTC"), "sightings.csv")
        self.assertEqual((data[0]["Date"], data[0]["Time"]), (str(in_utc.date()), in_utc.strftime("%H:%M:%S")))
        self.assertEqual(in_utc - datetime.datetime.combine(day, clock), datetime.timedelta(hours=7))   # July: daylight time

    def test_efforts_move_with_the_zone_too(self):
        effort = rows("""SELECT legacy_daily_effort_id, effort_date, start_time,
                                ((effort_date + start_time) AT TIME ZONE 'America/Los_Angeles') AT TIME ZONE 'UTC'
                         FROM app.daily_effort WHERE start_time >= '17:00' ORDER BY id LIMIT 1""")
        self.assertTrue(effort, "an Effort that starts at 5 pm Pacific or later is in UTC the next day")
        legacy_id, day, clock, in_utc = effort[0]
        self.add("effort", id=legacy_id)
        cols = ["", "date", "start_time"]
        _, utc = csv_rows(self.archive(("efforts",), tz="UTC", col_efforts=cols), "efforts.csv")
        _, pacific = csv_rows(self.archive(("efforts",), tz="Pacific", col_efforts=cols), "efforts.csv")
        self.assertEqual((pacific[0]["Date"], pacific[0]["Start Time"]), (str(day), clock.strftime("%H:%M:%S")))
        self.assertEqual((utc[0]["Date"], utc[0]["Start Time"]), (str(in_utc.date()), in_utc.strftime("%H:%M:%S")))
        self.assertNotEqual(utc[0]["Date"], pacific[0]["Date"])

    def test_a_tracks_start_and_end_are_utc_as_stored_and_move_in_pacific(self):
        track = rows("""SELECT e.legacy_daily_effort_id, t.start_time_utc, t.end_time_utc,
                               t.start_time_utc AT TIME ZONE 'UTC' AT TIME ZONE 'America/Los_Angeles',
                               t.end_time_utc AT TIME ZONE 'UTC' AT TIME ZONE 'America/Los_Angeles'
                        FROM app.track t JOIN app.daily_effort e ON e.id = t.daily_effort_id
                        WHERE t.start_time_utc IS NOT NULL AND t.end_time_utc IS NOT NULL
                          AND (SELECT count(*) FROM app.track x WHERE x.daily_effort_id = e.id) = 1
                        ORDER BY e.id LIMIT 1""")[0]
        self.add("effort", id=track[0])
        cols = ["", "track_start", "track_end"]
        wanted = lambda value: value.strftime("%Y-%m-%d %H:%M:%S")
        for zone, start, end in (("UTC", track[1], track[2]), ("Pacific", track[3], track[4])):
            _, data = csv_rows(self.archive(("efforts",), tz=zone, col_efforts=cols), "efforts.csv")
            self.assertEqual((data[0]["Track Start"], data[0]["Track End"]), (wanted(start), wanted(end)), zone)
        self.assertNotEqual(track[1], track[3])

    def test_the_attached_records_move_with_the_zone_too(self):
        tag = rows("""SELECT t."TagSummaryID", s.legacy_sighting_id, t."DeployDateTime",
                             t."DeployDateTime" AT TIME ZONE 'America/Los_Angeles' AT TIME ZONE 'UTC'
                      FROM dbo."TagSummaryT" t JOIN app.sighting s ON s.id = t.sighting_id
                      WHERE t."DeployDateTime"::time > '08:00' ORDER BY t."TagSummaryID" LIMIT 1""")[0]
        self.add("sighting", id=tag[1])
        wanted = lambda value: value.strftime("%Y-%m-%d %H:%M:%S")
        for zone, expected in (("Pacific", tag[2]), ("UTC", tag[3])):
            _, data = csv_rows(self.archive(("tags",), tz=zone), "tags.csv")
            self.assertIn(wanted(expected), [r["Deployed"] for r in data], zone)

    def test_the_two_date_formats(self):
        self.one_sighting()
        _, iso = csv_rows(self.archive(("sightings",), tz="Pacific", df="iso"), "sightings.csv")
        _, excel = csv_rows(self.archive(("sightings",), tz="Pacific", df="excel"), "sightings.csv")
        self.assertRegex(iso[0]["Date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(excel[0]["Date"], r"^\d{1,2}/\d{1,2}/\d{4}$")
        self.assertEqual(datetime.datetime.strptime(excel[0]["Date"], "%m/%d/%Y").date().isoformat(), iso[0]["Date"])

    def test_excel_keeps_dates_as_dates_and_numbers_as_numbers(self):
        from openpyxl import load_workbook
        self.one_sighting()
        sheet = load_workbook(io.BytesIO(body(self.download("xlsx", ["sightings"], df="excel"))))["Sightings"]
        headings = [c.value for c in sheet[1]]
        date, latitude = sheet.cell(2, headings.index("Date") + 1), sheet.cell(2, headings.index("Latitude") + 1)
        self.assertIsInstance(date.value, datetime.datetime)
        self.assertEqual(date.number_format, "m/d/yyyy")
        self.assertIsInstance(latitude.value, float)


class RelatedRecordsTests(ExportTest):
    """A query of Efforts can bring the Sightings of those Efforts, and a query
    of Sightings the Efforts of those Sightings. It is a choice for each query."""

    def an_effort_with_sightings(self, at_least=2):
        return column("""SELECT e.legacy_daily_effort_id FROM app.daily_effort e
                         JOIN app.sighting s ON s.daily_effort_id = e.id
                         WHERE e.research_group = 'CRC' GROUP BY 1 HAVING count(*) >= %s ORDER BY 1 LIMIT 1""",
                      [at_least])[0]

    def sightings_of(self, effort):
        return set(column("""SELECT s.legacy_sighting_id FROM app.sighting s
                             JOIN app.daily_effort e ON e.id = s.daily_effort_id
                             WHERE e.legacy_daily_effort_id = %s""", [effort]))

    def ids(self, name, key):
        _, data = csv_rows(self.archive((name,)), f"{name}.csv")
        return [int(r[key]) for r in data]

    def test_a_query_brings_its_related_records_unless_told_not_to(self):
        # The Add To Export buttons send nothing about it, so a click is on.
        for kind, qs in (("efforts", "year=2024"), ("sightings", "year=2024")):
            self.client.post("/export/add/", {"kind": kind, "qs": qs})
        for kind, number in (("effort", DailyEffort.objects.filter(research_group="CRC").first().legacy_daily_effort_id),
                             ("sighting", Sighting.objects.filter(research_group="CRC").first().legacy_sighting_id)):
            self.client.post("/export/add/", {"kind": kind, "id": number})
        self.client.post("/export/add/", {"kind": "explore", "qs": "year=2024"})
        stored = self.client.session[export_stack.KEY]
        self.assertEqual([e.get("related") for e in stored], [True, True, True, True, None])
        self.assertEqual([e["kind"] for e in stored], ["efforts", "sightings", "effort", "sighting", "explore"])

    def test_an_entry_from_before_the_choice_existed_brings_them_too(self):
        session = self.client.session
        session[export_stack.KEY] = [{"kind": "effort", "qs": "id=1", "label": "Effort 1"}]
        session.save()
        self.assertTrue(export_stack.brings_related(self.client.session[export_stack.KEY][0]))

    def test_an_efforts_sightings_come_with_it_and_not_when_off(self):
        effort = self.an_effort_with_sightings()
        expected = self.sightings_of(effort)
        self.assertGreaterEqual(len(expected), 2)

        self.add("effort", related="1", id=effort)
        self.assertEqual(set(self.ids("sightings", "Sighting ID")), expected)
        self.assertEqual(self.ids("efforts", "Effort ID"), [effort])
        counts = {s["key"]: s["rows"] for s in self.client.get("/export/").context["sheets"]}
        self.assertEqual((counts["efforts"], counts["sightings"]), (1, len(expected)))

        self.client.post("/export/related/", {"index": "0", "related": "0"})
        self.assertEqual(self.ids("sightings", "Sighting ID"), [])
        self.assertEqual(self.ids("efforts", "Effort ID"), [effort])
        counts = {s["key"]: s["rows"] for s in self.client.get("/export/").context["sheets"]}
        self.assertEqual(counts["sightings"], 0)

    def test_the_sightings_of_an_effort_are_all_of_them_whatever_the_filters(self):
        # The Effort page lists every Sighting of the Effort, so the export does.
        effort = column("""SELECT e.legacy_daily_effort_id FROM app.daily_effort e
                           JOIN app.sighting s ON s.daily_effort_id = e.id
                           JOIN app.species sp ON sp.id = s.species_id
                           WHERE sp.category = 'non_animal' LIMIT 1""")[0]
        self.add("effort", related="1", id=effort)
        self.assertEqual(set(self.ids("sightings", "Sighting ID")), self.sightings_of(effort))

    def test_a_sightings_efforts_come_with_it_and_not_when_off(self):
        sighting = column("""SELECT s.legacy_sighting_id FROM app.sighting s
                             WHERE s.research_group = 'CRC' AND s.daily_effort_id IS NOT NULL ORDER BY s.id LIMIT 1""")[0]
        effort = column("""SELECT e.legacy_daily_effort_id FROM app.daily_effort e
                           JOIN app.sighting s ON s.daily_effort_id = e.id
                           WHERE s.legacy_sighting_id = %s""", [sighting])[0]
        self.add("sighting", related="1", id=sighting)
        self.assertEqual(self.ids("efforts", "Effort ID"), [effort])
        self.assertEqual(self.ids("sightings", "Sighting ID"), [sighting])
        self.client.post("/export/related/", {"index": "0", "related": "0"})
        self.assertEqual(self.ids("efforts", "Effort ID"), [])
        self.assertEqual(self.ids("sightings", "Sighting ID"), [sighting])

    def test_a_sighting_with_no_effort_brings_none(self):
        found = column("SELECT legacy_sighting_id FROM app.sighting WHERE daily_effort_id IS NULL ORDER BY id LIMIT 1")
        if not found:
            self.skipTest("this copy of the data has no Sighting without an Effort")
        sighting = found[0]
        self.add("sighting", related="1", id=sighting)
        self.assertEqual(self.ids("efforts", "Effort ID"), [])
        self.assertEqual(self.ids("sightings", "Sighting ID"), [sighting])

    def test_a_sighting_query_brings_the_efforts_of_all_its_sightings_once(self):
        self.stack(("sightings", EXPLORE_QUERY), related="1")
        expected = set(column("""SELECT DISTINCT e.legacy_daily_effort_id FROM app.sighting s
                                 JOIN app.daily_effort e ON e.id = s.daily_effort_id
                                 WHERE s.legacy_sighting_id = ANY(%s)""", [list(crc_sightings([7, 8]))]))
        got = self.ids("efforts", "Effort ID")
        self.assertEqual(set(got), expected)
        self.assertEqual(len(got), len(expected))

    def test_the_choice_belongs_to_each_query(self):
        first, second = self.an_effort_with_sightings(), column("""
            SELECT e.legacy_daily_effort_id FROM app.daily_effort e JOIN app.sighting s ON s.daily_effort_id = e.id
            WHERE e.research_group = 'CRC' GROUP BY 1 HAVING count(*) >= 2 ORDER BY 1 OFFSET 5 LIMIT 1""")[0]
        self.add("effort", related="1", id=first)
        self.add("effort", related="0", id=second)
        stored = self.client.session[export_stack.KEY]
        self.assertEqual([e["related"] for e in stored], [True, False])
        # Only the first query's Sightings are in the export.
        self.assertEqual(set(self.ids("sightings", "Sighting ID")), self.sightings_of(first))
        first_counts, second_counts = self.client.get("/export/").context["queries"]
        self.assertEqual((first_counts["efforts"], first_counts["sightings"]), (1, len(self.sightings_of(first))))
        self.assertEqual((second_counts["efforts"], second_counts["sightings"]), (1, None))

    def test_the_matched_queries_column_counts_the_query_that_brought_a_row(self):
        effort = self.an_effort_with_sightings()
        everyone = sorted(self.sightings_of(effort))
        picked = everyone[0]
        self.add("effort", related="1", id=effort)         # query 1 brings every Sighting of the Effort
        self.add("sighting", related="0", id=picked)        # query 2 is one of them, bringing nothing more
        _, sightings = csv_rows(self.archive(("sightings",)), "sightings.csv")
        matched = {int(r["Sighting ID"]): r["Matched Queries"] for r in sightings}
        self.assertEqual(set(matched), set(everyone))
        self.assertEqual(len(sightings), len(everyone))     # each once
        self.assertEqual(matched[picked], "1, 2")
        self.assertEqual({v for k, v in matched.items() if k != picked}, {"1"})
        _, efforts = csv_rows(self.archive(("efforts",)), "efforts.csv")
        self.assertEqual([(int(r["Effort ID"]), r["Matched Queries"]) for r in efforts], [(effort, "1")])

        # Query 2 brings its Effort as well: the Effort now matches both.
        self.client.post("/export/related/", {"index": "1", "related": "1"})
        _, efforts = csv_rows(self.archive(("efforts",)), "efforts.csv")
        self.assertEqual([(int(r["Effort ID"]), r["Matched Queries"]) for r in efforts], [(effort, "1, 2")])

    def test_a_row_brought_by_the_tick_alone_names_that_query(self):
        sighting = column("""SELECT s.legacy_sighting_id FROM app.sighting s
                             WHERE s.research_group = 'CRC' AND s.daily_effort_id IS NOT NULL ORDER BY s.id LIMIT 1""")[0]
        other = column("""SELECT legacy_daily_effort_id FROM app.daily_effort WHERE research_group = 'CRC'
                          AND id NOT IN (SELECT daily_effort_id FROM app.sighting WHERE legacy_sighting_id = %s)
                          ORDER BY id LIMIT 1""", [sighting])[0]
        self.add("effort", related="0", id=other)
        self.add("sighting", related="1", id=sighting)
        _, efforts = csv_rows(self.archive(("efforts",)), "efforts.csv")
        got = {int(r["Effort ID"]): r["Matched Queries"] for r in efforts}
        self.assertEqual(sorted(got.values()), ["1", "2"])
        self.assertEqual(got[other], "1")

    def test_the_preview_follows_the_choice(self):
        effort = self.an_effort_with_sightings()
        self.add("effort", related="1", id=effort)
        data = self.client.get("/export/preview/?preview=sightings&format=csv").json()
        self.assertEqual(data["total"], len(self.sightings_of(effort)))
        self.assertTrue(data["rows"])
        self.client.post("/export/related/", {"index": "0", "related": "0"})
        data = self.client.get("/export/preview/?preview=sightings&format=csv").json()
        self.assertEqual((data["total"], data["rows"]), (0, []))

    def test_the_other_sheets_follow_the_records_that_came_in(self):
        effort = self.an_effort_with_sightings()
        self.add("effort", related="1", id=effort)
        expected = rows("""SELECT count(*) FROM app.sample sm JOIN app.sighting s ON s.id = sm.sighting_id
                           WHERE s.legacy_sighting_id = ANY(%s)""", [list(self.sightings_of(effort))])[0][0]
        counts = {s["key"]: s["rows"] for s in self.client.get("/export/").context["sheets"]}
        self.assertEqual(counts["samples"], expected)

    def test_the_page_offers_the_choice_where_it_means_something(self):
        self.stack(("efforts", "year=2024"), ("sightings", "year=2024"), ("explore", "year=2024"), related="1")
        self.add("effort", related="0", id=self.an_effort_with_sightings())
        response = self.client.get("/export/")
        html = response.content.decode()
        queries = response.context["queries"]
        self.assertEqual([q["related_label"] for q in queries],
                         ["Include The Sightings Of These Efforts", "Include The Efforts Of These Sightings",
                          None, "Include The Sightings Of These Efforts"])
        self.assertEqual([q["related"] for q in queries], [True, True, False, False])
        self.assertEqual(html.count("data-related="), 3)   # none for Explore
        self.assertRegex(html, r'data-related="0" checked>\s*Include The Sightings Of These Efforts')
        self.assertRegex(html, r'data-related="1" checked>\s*Include The Efforts Of These Sightings')
        self.assertRegex(html, r'data-related="3">\s*Include The Sightings Of These Efforts')

    def test_turning_it_on_or_off_is_a_post_that_goes_back_to_the_page(self):
        self.stack(("efforts", "year=2024"), ("explore", "year=2024"), related="1")
        response = self.client.post("/export/related/", {"index": "0", "related": "0",
                                                         "next": "/export/?format=csv&tz=Pacific"})
        self.assertRedirects(response, "/export/?format=csv&tz=Pacific", fetch_redirect_response=False)
        self.assertFalse(self.client.session[export_stack.KEY][0]["related"])
        self.client.post("/export/related/", {"index": "0", "related": "1"})
        self.assertTrue(self.client.session[export_stack.KEY][0]["related"])
        # Explore has no such choice, and a query that is not there is ignored.
        self.client.post("/export/related/", {"index": "1", "related": "0"})
        self.client.post("/export/related/", {"index": "9", "related": "0"})
        self.assertNotIn("related", self.client.session[export_stack.KEY][1])
        self.assertEqual(self.client.get("/export/related/").status_code, 405)
        self.client.logout()
        sign_in(self.client, "looker", "Viewer")
        self.assertEqual(self.client.post("/export/related/", {"index": "0", "related": "0"}).status_code, 403)


class RawGpsFileTests(ExportTest):
    """The raw files, from the files in storage. The tests' bucket holds a
    stand-in for each file, so these write real ones."""

    def setUp(self):
        super().setUp()
        track = (Track.objects.filter(daily_effort__research_group="CRC", object_key__isnull=False,
                                      track_status="available", daily_effort__effort_date__year=2024)
                 .annotate(n=Count("daily_effort__tracks")).filter(n=1).order_by("id").first())
        self.effort = track.daily_effort
        self.key = track.object_key
        self.text = ("datetime_utc,latitude,longitude\n"
                     "2024-07-01 14:30:00,34.1,-119.5\n"
                     "2024-07-01 14:30:01,34.2,-119.6\n")
        with open(track_objects._local_path(self.key), "w") as f:
            f.write(self.text)
        self.add("effort", id=self.effort.legacy_daily_effort_id)

    def raw(self, fmt="csv", sheets=("efforts",)):
        return zipfile.ZipFile(io.BytesIO(body(self.download(fmt, list(sheets), raw="1"))))

    def listing(self, archive):
        _, data = csv_rows(archive, "track_file_list.csv")
        return {(int(r["Effort ID"]), r["Track File"]): r["In The Tracks Folder"] for r in data}

    def test_the_gps_points_sheet_is_gone_but_the_files_are_not(self):
        response = self.client.get("/export/download/", {"format": "csv", "sheet": ["gps_points"]}, follow=True)
        self.assertContains(response, "Tick at least one sheet")   # an unknown sheet is not a sheet
        self.assertIn(f"tracks/{self.key}", self.raw().namelist())

    def test_the_raw_files_come_in_a_tracks_folder_for_any_format(self):
        for fmt in ("csv", "xlsx", "geojson", "gpx", "gpkg"):
            archive = self.raw(fmt)
            files = [n for n in archive.namelist() if n.startswith("tracks/")]
            self.assertEqual(files, [f"tracks/{self.key}"], fmt)
            self.assertEqual(archive.read(f"tracks/{self.key}").decode(), self.text, fmt)
            self.assertNotIn("gps_files/", "".join(archive.namelist()), fmt)

    def test_an_excel_download_with_the_files_is_a_zip_holding_the_workbook(self):
        response = self.download("xlsx", ["efforts"], raw="1")
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertRegex(response["Content-Disposition"], r'\.zip"')
        self.assertIn("cascadia_export.xlsx", zipfile.ZipFile(io.BytesIO(body(response))).namelist())
        plain = self.download("xlsx", ["efforts"])
        self.assertRegex(plain["Content-Disposition"], r'\.xlsx"')

    def test_the_page_says_where_the_files_go_and_how_many(self):
        response = self.client.get("/export/")
        html = response.content.decode()
        self.assertContains(response, "Include The Raw GPS Files Of These Efforts")
        self.assertContains(response, "in a folder called tracks")
        self.assertContains(response, "track_file_list.csv")
        self.assertContains(response, 'id="raw-zip" hidden')
        self.assertEqual(response.context["track_files"], 1)
        self.assertIn("1 file for the 1 Effort in this export", " ".join(html.split()))

    def test_a_list_names_what_happened_to_each_effort(self):
        archive = self.raw()
        self.assertEqual(self.listing(archive), {(self.effort.legacy_daily_effort_id, self.key): "Yes"})

    def test_every_track_of_the_efforts_is_included_not_only_the_first(self):
        legacy_id = column("""
            SELECT e.legacy_daily_effort_id FROM app.daily_effort e
            WHERE e.id IN (SELECT daily_effort_id FROM dbo."TrackT" GROUP BY 1
                           HAVING count(*) > 1 AND count(DISTINCT file_name) > 1)
            ORDER BY 1 LIMIT 1""")[0]
        keys = column("""SELECT object_key FROM app.track WHERE track_status = 'available' AND daily_effort_id =
                         (SELECT id FROM app.daily_effort WHERE legacy_daily_effort_id = %s)""", [legacy_id])
        for key in keys:
            path = track_objects._local_path(key)
            if not os.path.isfile(path):
                with open(path, "w") as f:
                    f.write("datetime_utc,latitude,longitude\n")
        self.client.post("/export/remove/", {"index": "0"})
        self.add("effort", id=legacy_id)
        files = {n.split("/", 1)[1] for n in self.raw().namelist() if n.startswith("tracks/")}
        self.assertTrue(keys and set(keys) <= files)

    def test_a_file_the_bucket_lacks_is_listed_not_silently_dropped(self):
        os.unlink(track_objects._local_path(self.key))
        archive = self.raw()
        self.assertNotIn(f"tracks/{self.key}", archive.namelist())
        self.assertEqual(self.listing(archive),
                         {(self.effort.legacy_daily_effort_id, self.key): "No: the file is not in file storage"})

    def test_without_storage_the_list_says_why(self):
        with mock.patch.object(track_objects, "configured", return_value=False):
            archive = self.raw()
        self.assertEqual([n for n in archive.namelist() if n.startswith("tracks/")], [])
        self.assertIn("not set up", list(self.listing(archive).values())[0])

    def test_an_effort_with_no_track_and_one_with_a_blank_track_are_skipped_and_named(self):
        no_track = column("""SELECT e.legacy_daily_effort_id FROM app.daily_effort e
                             WHERE e.research_group = 'CRC' AND NOT EXISTS (SELECT 1 FROM app.track t WHERE t.daily_effort_id = e.id)
                             ORDER BY e.id LIMIT 1""")[0]
        blank, blank_key = rows("""SELECT e.legacy_daily_effort_id, t.object_key FROM app.daily_effort e
                                   JOIN app.track t ON t.daily_effort_id = e.id
                                   WHERE e.research_group = 'CRC' AND t.track_status = 'blank'
                                   ORDER BY e.id LIMIT 1""")[0]
        # The blank track's file is there, with a heading and no points, and still is not copied.
        with open(track_objects._local_path(blank_key), "w") as f:
            f.write("datetime_utc,latitude,longitude\n")
        self.add("effort", id=no_track)
        self.add("effort", id=blank)
        archive = self.raw()
        self.assertEqual([n for n in archive.namelist() if n.startswith("tracks/")], [f"tracks/{self.key}"])
        listed = self.listing(archive)
        self.assertEqual(listed[(no_track, "")], "No: the Effort has no track file")
        self.assertEqual(listed[(blank, blank_key)], "No: the track is blank, with no points")
        self.assertEqual(listed[(self.effort.legacy_daily_effort_id, self.key)], "Yes")

    def test_the_efforts_a_sighting_query_brings_in_have_their_files_included(self):
        sighting = column("""SELECT s.legacy_sighting_id FROM app.sighting s
                             JOIN app.track t ON t.daily_effort_id = s.daily_effort_id
                             WHERE s.research_group = 'CRC' AND t.track_status = 'available' AND t.object_key <> %s
                             ORDER BY s.id LIMIT 1""", [self.key])[0]
        key = column("""SELECT t.object_key FROM app.sighting s JOIN app.track t ON t.daily_effort_id = s.daily_effort_id
                        WHERE s.legacy_sighting_id = %s AND t.track_status = 'available' ORDER BY t.legacy_track_id LIMIT 1""",
                     [sighting])[0]
        with open(track_objects._local_path(key), "w") as f:
            f.write(self.text)
        self.client.post("/export/remove/", {"index": "0"})
        self.add("sighting", related="1", id=sighting)
        self.assertIn(f"tracks/{key}", self.raw().namelist())
        # With the choice off the Sighting brings no Effort, so no file.
        self.client.post("/export/related/", {"index": "0", "related": "0"})
        archive = self.raw(sheets=("sightings",))
        self.assertEqual([n for n in archive.namelist() if n.startswith("tracks/")], [])
        self.assertEqual(csv_rows(archive, "track_file_list.csv")[1], [])

    def test_a_name_is_a_plain_file_name_that_is_never_taken_twice(self):
        name = export_sheets._entry_name
        self.assertEqual(name("2024/20240701-ROB.csv", set()), "20240701-ROB.csv")
        self.assertEqual(name("2025/dup.csv", {"dup.csv"}), "2025_dup.csv")
        self.assertEqual(name("dup.csv", {"dup.csv"}), "track_file_2.csv")
        for key in ("..", ".", "", "a/..", "a/.", "a/", "/", "\\", "...", "x\\.."):
            result = name(key, set())
            self.assertTrue(result.strip("."), key)
            self.assertNotIn("/", result, key)
            self.assertNotIn("\\", result, key)
        # A numbered name does not meet another numbered name.
        self.assertEqual(name("..", {"track_file_2.csv"}), "track_file_3.csv")
        # Nor does a folder in the key survive in the name.
        self.assertEqual(name("a\\b\\c.csv", set()), "c.csv")

    def test_two_files_of_one_name_and_a_bad_name_are_all_kept_and_listed_as_written(self):
        def available(skip):
            return (Track.objects.filter(track_status="available", daily_effort__research_group="CRC",
                                         daily_effort__effort_date__year=2024)
                    .exclude(pk__in=skip).exclude(daily_effort=self.effort)
                    .annotate(n=Count("daily_effort__tracks")).filter(n=1).order_by("id").first())
        mine = Track.objects.get(daily_effort=self.effort)
        second = available([])
        third = available([second.pk])
        for track, key in ((mine, "2024/dup.csv"), (second, "2025/dup.csv"), (third, "..")):
            with connection.cursor() as cur:
                cur.execute("UPDATE app.track SET object_key = %s WHERE id = %s", [key, track.pk])
        self.add("effort", id=second.daily_effort.legacy_daily_effort_id)
        self.add("effort", id=third.daily_effort.legacy_daily_effort_id)

        with mock.patch.object(track_objects, "fetch", lambda wanted: ((k, b"x") for k in wanted)):
            archive = self.raw()
        in_folder = sorted(n for n in archive.namelist() if n.startswith("tracks/"))
        self.assertEqual(in_folder, ["tracks/2025_dup.csv", "tracks/dup.csv", "tracks/track_file_1.csv"])
        for entry in archive.namelist():
            self.assertNotIn("..", entry.split("/"), entry)
            self.assertNotIn("", entry.split("/"), entry)

        _, listing = csv_rows(archive, "track_file_list.csv")
        by_effort = {int(r["Effort ID"]): r for r in listing}
        efforts = [t.daily_effort.legacy_daily_effort_id for t in (mine, second, third)]
        self.assertEqual([(by_effort[e]["Track File"], by_effort[e]["Name In The Tracks Folder"]) for e in efforts],
                         [("dup.csv", "dup.csv"), ("dup.csv", "2025_dup.csv"), ("..", "track_file_1.csv")])
        self.assertEqual({by_effort[e]["In The Tracks Folder"] for e in efforts}, {"Yes"})
        # Every name the list gives is a real entry, and the other way round.
        self.assertEqual({f"tracks/{r['Name In The Tracks Folder']}" for r in listing
                          if r["Name In The Tracks Folder"]}, set(in_folder))

    def test_efforts_in_two_queries_give_a_file_once(self):
        self.add("efforts", "year=2024&month=7")
        self.assertEqual(self.raw().namelist().count(f"tracks/{self.key}"), 1)


class LargeExportTests(ExportTest):
    """Rows are fetched a batch at a time through a server-side cursor, and
    the file is written as they arrive. The writers' own memory use is
    measured in Django/unit_tests/test_export.py."""

    def test_rows_are_fetched_in_batches_not_all_at_once(self):
        self.stack(("sightings", "research_group=all&include_non_animal=1"))
        plan = self.plan()
        total = export_sheets.BY_KEY["sightings"].count(plan)
        self.assertGreater(total, 100)

        fetched, opened = [], []
        real = connection.chunked_cursor

        class Spy:
            def __init__(self, cursor):
                self.cursor = cursor
            def __enter__(self):
                self.cursor.__enter__()
                return self
            def __exit__(self, *args):
                return self.cursor.__exit__(*args)
            def execute(self, *args):
                return self.cursor.execute(*args)
            def fetchmany(self, size):
                batch = self.cursor.fetchmany(size)
                fetched.append(len(batch))
                return batch

        def spy():
            opened.append(1)
            return Spy(real())

        with mock.patch.object(export_sheets, "BATCH", 25), mock.patch.object(connection, "chunked_cursor", spy):
            taken = []
            for row in export_sheets.BY_KEY["sightings"].rows(plan, export_sheets.Zone("UTC")):
                taken.append(row)
                if len(taken) == 30:
                    break
        self.assertEqual(len(opened), 1)
        self.assertEqual(fetched, [25, 25])      # two batches, with thousands of rows still on the server
        self.assertLess(sum(fetched), total)

    def test_a_whole_sheet_is_written_without_being_listed_first(self):
        self.stack(("sightings", "research_group=all&include_non_animal=1"))
        plan = self.plan()
        choice = export_sheets.Choice(sheets=["sightings"])
        out = export_sheets.shape(export_sheets.BY_KEY["sightings"], plan, choice)
        self.assertEqual(type(out.rows).__name__, "generator")
        first = next(out.rows)
        self.assertEqual(len(first[0]), len(out.headers))
