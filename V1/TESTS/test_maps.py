"""The maps: what a clicked track's popup is sent, and the track file names
on an Effort page, with and without the permission to open Cascadia Admin."""

from django.db.models import Count
from django.test import TestCase
from django.urls import reverse

from survey.models import DailyEffort, Track
from TESTS.test_permissions import sign_in

POPUP_FIELDS = {"track", "effort", "label", "date", "vessel", "group",
                "object_key", "points", "length_nm"}


def an_effort_with_several_tracks():
    return (DailyEffort.objects
            .annotate(n=Count("tracks"))
            .filter(n__gt=1, tracks__geom__isnull=False,
                    tracks__object_key__isnull=False)
            .order_by("legacy_daily_effort_id")
            .first())


class TrackPopupTests(TestCase):

    def setUp(self):
        self.effort = an_effort_with_several_tracks()
        self.tracks = list(self.effort.tracks.filter(geom__isnull=False)
                           .select_related("daily_effort__vessel"))

    def test_api_tracks_sends_what_the_popup_shows(self):
        sign_in(self.client, "viewer", "Viewer")
        day = self.effort.effort_date
        data = self.client.get("/api/tracks/", {"date_from": day, "date_to": day}).json()
        sent = {f["properties"]["track"]: f["properties"] for f in data["features"]}

        for track in self.tracks:
            p = sent[track.legacy_track_id]
            self.assertEqual(set(p) - {"suspect"}, POPUP_FIELDS)
            self.assertEqual(p["effort"], self.effort.legacy_daily_effort_id)
            self.assertEqual(p["object_key"], track.object_key)
            self.assertEqual(p["date"], str(self.effort.effort_date))
            self.assertEqual(p["vessel"], self.effort.vessel.label if self.effort.vessel else None)
            self.assertEqual(p["group"], track.research_group or self.effort.research_group)
            self.assertEqual(p["points"], track.point_count)
            self.assertEqual(p["length_nm"], round(float(track.length_nm), 1)
                             if track.length_nm is not None else None)
            self.assertEqual(p.get("suspect", False), track.length_is_plausible is False)

    def test_the_effort_map_is_given_every_track(self):
        sign_in(self.client, "viewer", "Viewer")
        html = self.client.get(f"/efforts/{self.effort.legacy_daily_effort_id}/").content.decode()
        for track in self.tracks:
            self.assertIn(f'"track": {track.legacy_track_id}', html)


class TrackFileNameTests(TestCase):

    def setUp(self):
        self.effort = an_effort_with_several_tracks()
        self.url = f"/efforts/{self.effort.legacy_daily_effort_id}/"
        self.names = [t.file_name for t in self.effort.tracks.all() if t.file_name]

    def test_a_viewer_sees_the_file_names_as_plain_text(self):
        sign_in(self.client, "viewer", "Viewer")
        html = self.client.get(self.url).content.decode()
        for name in self.names:
            self.assertIn(name, html)
        self.assertNotIn(reverse("admin_tracks"), html)
        self.assertIn("trackManagerUrl: null", html)

    def test_a_data_manager_opens_each_file_in_the_track_file_manager(self):
        sign_in(self.client, "manager", "Data Manager")
        html = self.client.get(self.url).content.decode()
        for track in self.effort.tracks.filter(object_key__isnull=False):
            self.assertIn(f'href="{reverse("admin_tracks")}?open={track.legacy_track_id}"', html)
        self.assertIn(f'trackManagerUrl: "{reverse("admin_tracks")}"', html)

    def test_explore_offers_the_track_file_manager_only_with_the_permission(self):
        sign_in(self.client, "viewer", "Viewer")
        self.assertIn("trackManagerUrl: null",
                      self.client.get("/explore/").content.decode())
        self.client.logout()
        sign_in(self.client, "manager", "Data Manager")
        self.assertIn(f'trackManagerUrl: "{reverse("admin_tracks")}"',
                      self.client.get("/explore/").content.decode())


class FileNameTests(TestCase):

    def test_the_file_name_leaves_out_the_folder(self):
        self.assertEqual(Track(object_key="tracks/2020/a b.csv").file_name, "a b.csv")
        self.assertEqual(Track(object_key="a.csv").file_name, "a.csv")
        self.assertIsNone(Track(object_key=None).file_name)
