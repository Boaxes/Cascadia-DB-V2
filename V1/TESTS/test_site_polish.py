"""How the pages write what people read: chevrons, Title Case, separators."""

import os
import re

from django.conf import settings
from django.db import connection
from django.test import TestCase

from survey.models import DailyEffort, Sighting, Track
from TESTS.test_permissions import sign_in

ARROWS = re.compile("[←-⇿]|&[lrud]arr;")


class ListPageTests(TestCase):

    def setUp(self):
        sign_in(self.client, "viewer", "Viewer")

    def test_the_sorted_column_has_a_chevron_not_an_arrow_letter(self):
        for url, down in (("/efforts/", "sort-ind down"), ("/sightings/", "sort-ind down")):
            html = self.client.get(url).content.decode()
            self.assertIn(down, html, url)
            self.assertIsNone(ARROWS.search(html), url)
        html = self.client.get("/efforts/?sort=date").content.decode()
        self.assertIn("sort-ind up", html)

    def test_filter_labels_are_in_title_case(self):
        html = self.client.get("/efforts/").content.decode()
        for label in ("Survey Type", "GPS Track", "Crew Member", "All Regions", "All Localities",
                      "Apply Filters", "Exact Dates", "No Track File"):
            self.assertIn(label, html, label)
        for old in ("Survey type", "GPS track", "Crew member", "All regions", "All localities",
                    "Apply filters", "Exact dates", "No track file"):
            self.assertNotIn(old, html, old)


class RecordPageTests(TestCase):

    def setUp(self):
        sign_in(self.client, "viewer", "Viewer")
        self.effort = (DailyEffort.objects
                       .filter(tracks__point_count__gte=1000).order_by("legacy_daily_effort_id").first())
        self.sighting = Sighting.objects.filter(est_size_best__gte=1000).order_by("legacy_sighting_id").first()

    def test_the_way_back_to_the_list_is_a_chevron_and_words(self):
        html = self.client.get(f"/efforts/{self.effort.legacy_daily_effort_id}/").content.decode()
        self.assertIn('class="back-link"', html)
        self.assertIn(">All Efforts</a>", html)
        self.assertIsNone(ARROWS.search(html))
        html = self.client.get(f"/sightings/{self.sighting.legacy_sighting_id}/").content.decode()
        self.assertIn(">All Sightings</a>", html)
        self.assertIsNone(ARROWS.search(html))

    def test_the_pop_over_back_button_is_words_only(self):
        html = self.client.get("/explore/").content.decode()
        self.assertIn('<button class="modal-back" type="button" hidden>Back</button>', html)

    def test_point_counts_have_separators(self):
        track = self.effort.tracks.filter(point_count__gte=1000).first()
        html = self.client.get(f"/efforts/{self.effort.legacy_daily_effort_id}/").content.decode()
        self.assertIn(f"{track.point_count:,}", html)
        self.assertNotIn(f">{track.point_count}<", html)

    def test_a_large_group_size_has_separators(self):
        html = self.client.get(f"/sightings/{self.sighting.legacy_sighting_id}/").content.decode()
        self.assertIn(f"{self.sighting.est_size_best:,}", html)

    def test_labels_are_in_title_case(self):
        html = self.client.get(f"/efforts/{self.effort.legacy_daily_effort_id}/").content.decode()
        for label in ("Sub-Area", "Survey Type", "Time Searching", "GPS Track File",
                      "Off Effort", "Research Group"):
            self.assertIn(f"<dt>{label}</dt>", html, label)
        self.assertIn("<h2>Extra Info</h2>", html)
        self.assertNotIn(">suspect<", html)
        html = self.client.get(f"/sightings/{self.sighting.legacy_sighting_id}/").content.decode()
        for label in ("Group Size", "Extra Info", "Group Behaviour", "Photos Taken", "Research Group"):
            self.assertIn(label, html, label)


class HistoryWindowTests(TestCase):

    def test_a_whole_record_action_is_named_in_title_case(self):
        sighting = Sighting.objects.order_by("legacy_sighting_id").first()
        with connection.cursor() as cur:
            cur.execute("""INSERT INTO app.audit_log (actor_name, action, target_table, target_pk, changes)
                           VALUES ('Someone', 'edit_file', 'SightingT', %s, '{}'::jsonb)""", [str(sighting.pk)])
        sign_in(self.client, "viewer", "Viewer")
        html = self.client.get(f"/sightings/{sighting.legacy_sighting_id}/").content.decode()
        self.assertIn('<span class="prov-field">Edited File</span>', html)
        self.assertNotIn('edit_file', html)


class ExploreTests(TestCase):

    def test_the_counts_have_separators(self):
        sign_in(self.client, "viewer", "Viewer")
        html = self.client.get("/explore/", {"research_group": "all"}).content.decode()
        total = Sighting.objects.count()
        self.assertGreater(total, 999)
        self.assertRegex(html, r"[\d,]+ Sightings")
        self.assertNotRegex(html, r">\d{4,} Sightings")

    def test_the_script_says_one_animal_and_two_animals(self):
        js = open(os.path.join(settings.BASE_DIR, "static", "survey", "explore.js"), encoding="utf-8").read()
        self.assertIn('plural(row.size, "Animal")', js)
        self.assertNotIn("' Animals</span>'", js)


class DownloadLabelTests(TestCase):

    def test_the_export_format_is_labelled_download_as(self):
        sign_in(self.client, "manager", "Data Manager")
        html = self.client.get("/export/").content.decode()
        self.assertIn('<label for="fmt">Download As</label>', html)


class StatusNameTests(TestCase):

    def test_track_status_names_are_in_title_case(self):
        for label in Track.STATUS_LABELS.values():
            self.assertEqual(label, label.title(), label)
