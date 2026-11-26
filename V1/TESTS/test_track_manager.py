"""
The Track File Manager: its pages and JSON, the one-track-per-Effort rule, the
Effort page's Add, Edit and Delete, blank files, and that every change is in the
Audit Log and can be put back.

Each test runs in a transaction rolled back afterwards, and the bucket is the
test run's stand-in folder (config/test_runner.py); WritePathTest removes what a
test adds to it and puts back what it changes.
"""

import datetime
import io
import json
import os
import shutil
from unittest import mock

from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection
from django.db.models import Count
from django.test import Client

from datahealth import trackfix
from datahealth.gps import tracks
from survey import track_checks, track_objects
from survey.models import DailyEffort, EffortTimeline, Track
from TESTS.test_permissions import PermissionTest, sign_in
from TESTS.test_write_paths import (CLEANED, GPS_FILE, WritePathTest, an_effort_with_no_track,
                                    an_unlinked_file, audit_comment, audit_entries, fetch_one, geometry)

API = "/cascadia-admin/tracks/api"


def a_matched_track():
    """A track with points, matched to an Effort, with a file of its own in the
    stand-in bucket (no other track names the same file)."""
    return (Track.objects.filter(daily_effort__isnull=False, track_status="available",
                                 vessel__isnull=False, survey_date__isnull=False)
            .exclude(object_key__in=_shared_names())
            .order_by("legacy_track_id").first())


def _shared_names():
    with connection.cursor() as cur:
        cur.execute("SELECT object_key FROM app.track GROUP BY lower(object_key), object_key "
                    "HAVING count(*) > 1")
        return [r[0] for r in cur.fetchall()]


def a_blank_track():
    return (Track.objects.filter(daily_effort__isnull=False, track_status="blank")
            .order_by("legacy_track_id").first())


def _several():
    """The Efforts that had more than one track file before the rule."""
    with connection.cursor() as cur:
        cur.execute("SELECT daily_effort_id FROM app.track WHERE daily_effort_id IS NOT NULL "
                    "GROUP BY 1 HAVING count(*) > 1 ORDER BY 1")
        return list(DailyEffort.objects.filter(pk__in=[r[0] for r in cur.fetchall()])
                    .order_by("legacy_daily_effort_id"))


def an_effort_with_one_track():
    with connection.cursor() as cur:
        cur.execute("SELECT daily_effort_id FROM app.track WHERE daily_effort_id IS NOT NULL "
                    "GROUP BY 1 HAVING count(*) = 1 ORDER BY 1 LIMIT 1")
        return DailyEffort.objects.get(pk=cur.fetchone()[0])


def gps_text(first="2024-09-24 16:00:00", count=4):
    """A cleaned file of `count` points a minute apart, from `first`, off Oregon."""
    start = datetime.datetime.fromisoformat(first)
    rows = [f"{start + datetime.timedelta(minutes=i):%Y-%m-%d %H:%M:%S},{42.05 + i / 1000:.6f},-124.27"
            for i in range(count)]
    return "datetime_utc,latitude,longitude\n" + "\n".join(rows) + "\n"


def file_of(name, text):
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


class ManagerTest(WritePathTest):

    def post(self, path, data=None, **extra):
        return self.client.post(f"{API}/{path}", data or {}, **extra)

    def get(self, path):
        return self.client.get(f"{API}/{path}")

    def stored(self, key):
        with open(os.path.join(self.bucket, key), "rb") as f:
            return f.read().decode("utf-8")

    def versions(self, key):
        folder = os.path.join(self.bucket, "_versions", key)
        return sorted(os.listdir(folder)) if os.path.isdir(folder) else []

    def entries(self, track):
        return audit_entries("TrackT", track.legacy_track_id)


class ExplorerTests(ManagerTest):

    def test_the_explorer_lists_every_file_a_page_at_a_time(self):
        data = self.get("files/").json()
        self.assertEqual(data["total"], Track.objects.exclude(object_key__isnull=True).count())
        self.assertGreater(data["all"], 1500)
        self.assertEqual(len(data["files"]), 100)
        again = self.client.get(f"{API}/files/", {"offset": 100}).json()
        self.assertEqual(len(again["files"]), 100)
        self.assertFalse({f["id"] for f in data["files"]} & {f["id"] for f in again["files"]})
        self.assertEqual(set(data["files"][0]), {"id", "name", "date", "vessel", "state"})

    def test_the_filters_are_applied_on_the_server(self):
        sizes = {state: self.client.get(f"{API}/files/", {"status": state}).json()["total"]
                 for state in ("matched", "unmatched", "blank")}
        self.assertEqual(sum(sizes.values()), self.get("files/").json()["total"])
        self.assertTrue(all(sizes.values()), sizes)
        blank = self.client.get(f"{API}/files/", {"status": "blank"}).json()["files"]
        self.assertTrue(all(f["state"] == "blank" for f in blank))

        track = a_matched_track()
        found = self.client.get(f"{API}/files/", {"q": track.object_key[:20].lower()}).json()["files"]
        self.assertIn(track.legacy_track_id, [f["id"] for f in found])
        by_vessel = self.client.get(f"{API}/files/", {"vessel": track.vessel.code,
                                                       "year": track.survey_date.year}).json()["files"]
        self.assertTrue(by_vessel)
        self.assertTrue(all(f["vessel"] == track.vessel.code and f["date"][:4] == str(track.survey_date.year)
                            for f in by_vessel))

    def test_the_page_offers_the_three_statuses_and_the_import_button(self):
        html = self.client.get("/cascadia-admin/tracks/").content.decode()
        for label in ("Track Files", "Import Files", "Fill From File", "All Status", "Matched",
                      "Not Matched", "Blank", "All Vessels", "All Years", "Revert", "Save", "Delete"):
            self.assertIn(label, html, label)
        self.assertNotIn("Missing File", html)
        self.assertNotIn("File Missing", html)

    def test_a_file_opens_with_its_text_effort_and_the_efforts_to_pick_from(self):
        track = a_matched_track()
        data = self.get(f"{track.legacy_track_id}/").json()
        self.assertEqual((data["id"], data["name"], data["state"]),
                         (track.legacy_track_id, track.object_key, "matched"))
        self.assertEqual(data["effort"]["id"], track.daily_effort.legacy_daily_effort_id)
        self.assertIn(track.daily_effort.legacy_daily_effort_id, [e["id"] for e in data["efforts"]])
        self.assertTrue(data["text"].startswith("datetime_utc,latitude,longitude"))
        self.assertEqual(data["history"], [])

    def test_a_blank_file_opens_as_the_header_alone(self):
        track = a_blank_track()
        data = self.get(f"{track.legacy_track_id}/").json()
        self.assertEqual((data["state"], data["blank"], data["text"]),
                         ("blank", True, "datetime_utc,latitude,longitude\n"))


class SaveTests(ManagerTest):

    def test_a_save_writes_the_file_keeps_one_version_and_logs_one_entry(self):
        track = a_matched_track()
        self.watch(track.object_key)
        before = self.stored(track.object_key)

        data = self.post(f"{track.legacy_track_id}/save/", {"text": gps_text(count=6)}).json()

        self.assertTrue(data["ok"], data)
        self.assertEqual(self.stored(track.object_key), gps_text(count=6))
        [kept] = self.versions(track.object_key)
        with open(os.path.join(self.bucket, "_versions", track.object_key, kept)) as f:
            self.assertEqual(f.read(), before)
        [(_id, action, actor, changes)] = self.entries(track)
        self.assertEqual((action, actor), ("edit_file", "Test Er"))
        self.assertEqual(changes["version"]["new"], f"_versions/{track.object_key}/{kept}")
        self.assertEqual(changes["point_count"]["new"], 6)
        # The line, the counts and the times are worked out again.
        after = Track.objects.get(pk=track.pk)
        self.assertEqual((after.point_count, after.track_status), (6, "available"))
        self.assertEqual(geometry(track.object_key)[1], 6)
        self.assertEqual(data["history"][0]["version"], f"_versions/{track.object_key}/{kept}")

    def test_many_edits_in_the_editor_are_one_save_and_one_version(self):
        # The editor holds every keystroke; only the text it sends is saved.
        track = a_matched_track()
        self.watch(track.object_key)
        text = gps_text(count=3)
        for i in range(50):
            text = text.replace("-124.27", f"-124.{270 + i}", 1)
        self.post(f"{track.legacy_track_id}/save/", {"text": text})
        self.assertEqual(len(self.versions(track.object_key)), 1)
        self.assertEqual(len(self.entries(track)), 1)

    def test_a_second_save_keeps_a_second_version(self):
        track = a_matched_track()
        self.watch(track.object_key)
        self.post(f"{track.legacy_track_id}/save/", {"text": gps_text(count=3)})
        self.post(f"{track.legacy_track_id}/save/", {"text": gps_text(count=5)})
        self.assertEqual(len(self.versions(track.object_key)), 2)
        self.assertEqual([e[1] for e in self.entries(track)], ["edit_file", "edit_file"])

    def test_bad_lines_are_refused_with_the_line_numbers_and_nothing_is_written(self):
        track = a_matched_track()
        self.watch(track.object_key)
        before = self.stored(track.object_key)
        bad = gps_text(count=3).replace("42.051000", "4278.12")

        response = self.post(f"{track.legacy_track_id}/save/", {"text": bad})

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertEqual([line for line, _why in data["errors"]], [3])
        self.assertIn("outside -90 to 90", data["errors"][0][1])
        self.assertEqual(self.stored(track.object_key), before)
        self.assertEqual(self.versions(track.object_key), [])
        self.assertEqual(self.entries(track), [])

    def test_saving_what_is_already_there_is_refused(self):
        track = a_matched_track()
        text = self.get(f"{track.legacy_track_id}/").json()["text"]
        response = self.post(f"{track.legacy_track_id}/save/", {"text": text})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Nothing has changed", response.json()["message"])
        self.assertEqual(self.entries(track), [])

    def test_a_blank_file_is_saved_into_and_a_file_with_no_points_is_blank(self):
        track = a_blank_track()
        self.assertTrue(self.post(f"{track.legacy_track_id}/save/", {"text": gps_text()}).json()["ok"])
        self.assertEqual(Track.objects.get(pk=track.pk).track_status, "available")
        # With no stored file there was nothing to keep as a version.
        self.assertEqual(self.versions(track.object_key), [])
        self.post(f"{track.legacy_track_id}/save/", {"text": "datetime_utc,latitude,longitude\n"})
        again = Track.objects.get(pk=track.pk)
        self.assertEqual((again.track_status, again.point_count, again.geom), ("blank", 0, None))
        self.assertEqual(self.get(f"{track.legacy_track_id}/").json()["state"], "blank")

    def test_an_earlier_version_can_be_read_back_and_only_this_files(self):
        track = a_matched_track()
        self.watch(track.object_key)
        before = self.stored(track.object_key)
        self.post(f"{track.legacy_track_id}/save/", {"text": gps_text()})
        version = self.get(f"{track.legacy_track_id}/").json()["history"][0]["version"]

        data = self.client.get(f"{API}/{track.legacy_track_id}/version/", {"key": version}).json()
        self.assertEqual(data["text"], before)
        other = self.client.get(f"{API}/{track.legacy_track_id}/version/", {"key": "_versions/other.csv/x.csv"})
        self.assertEqual(other.status_code, 404)

    def test_saving_it_back_makes_the_history_say_so(self):
        track = a_matched_track()
        self.watch(track.object_key)
        self.post(f"{track.legacy_track_id}/save/", {"text": gps_text()})
        history = self.get(f"{track.legacy_track_id}/").json()["history"]
        self.assertEqual([(h["what"], h["who"]) for h in history], [("Saved", "Test Er")])


class FillTests(ManagerTest):

    def test_the_preview_shows_both_lines_and_changes_nothing(self):
        track = a_matched_track()
        self.watch(track.object_key)
        before = self.stored(track.object_key)

        data = self.post(f"{track.legacy_track_id}/fill/preview/",
                         {"file": SimpleUploadedFile("from-unit.csv", GPS_FILE)}).json()

        self.assertTrue(data["ok"], data)
        self.assertEqual(data["new"]["points"], 5)
        self.assertEqual(data["dropped"], 2)
        self.assertEqual((data["new"]["first"], data["new"]["last"]),
                         ("2020-07-01 09:05:00", "2020-07-01 09:56:00"))
        self.assertEqual(len(data["new"]["line"]), 5)
        self.assertGreater(data["new"]["nm"], 0)
        self.assertEqual(set(data["current"]), {"points", "first", "last", "nm", "errors", "line"})
        self.assertEqual(self.stored(track.object_key), before)
        self.assertEqual(self.entries(track), [])

    def test_confirming_replaces_the_points_keeps_the_match_and_logs_it(self):
        track = a_matched_track()
        self.watch(track.object_key)

        data = self.post(f"{track.legacy_track_id}/fill/",
                         {"file": SimpleUploadedFile("from-unit.csv", GPS_FILE)}).json()

        self.assertTrue(data["ok"], data)
        self.assertEqual(self.stored(track.object_key), CLEANED)
        again = Track.objects.get(pk=track.pk)
        self.assertEqual((again.daily_effort_id, again.point_count), (track.daily_effort_id, 5))
        self.assertEqual(len(self.versions(track.object_key)), 1)
        [(_id, action, _actor, _changes)] = self.entries(track)
        self.assertEqual(action, "edit_file")
        comment = fetch_one("SELECT comment FROM app.audit_log WHERE target_table = 'TrackT' "
                            "AND target_pk = %s", [str(track.legacy_track_id)])[0]
        self.assertIn("from-unit.csv", comment)
        self.assertNotIn("DB167", comment)

    def test_a_file_with_nothing_usable_is_refused(self):
        track = a_matched_track()
        response = self.post(f"{track.legacy_track_id}/fill/preview/",
                             {"file": SimpleUploadedFile("empty.csv", b"datetime_utc,latitude,longitude\n")})
        self.assertEqual(response.status_code, 400)
        self.assertIn("no usable GPS rows", response.json()["message"])

    def test_a_blank_file_can_be_filled(self):
        track = a_blank_track()
        data = self.post(f"{track.legacy_track_id}/fill/", {"file": SimpleUploadedFile("x.csv", GPS_FILE)}).json()
        self.assertTrue(data["ok"], data)
        self.assertEqual(data["state"], "matched")
        self.assertEqual(Track.objects.get(pk=track.pk).point_count, 5)


class ImportTests(ManagerTest):

    def an_effort_and_a_file(self, **kwargs):
        effort = an_effort_with_no_track()
        name = f"{effort.effort_date:%Y%m%d}-{effort.vessel.code}-from-unit.csv"
        text = gps_text(f"{effort.effort_date:%Y-%m-%d} 18:00:00", **kwargs)
        return effort, name, text

    def preview(self, *files):
        return self.client.post(f"{API}/import/preview/", {"files": list(files)}).json()["files"]

    def test_a_file_is_suggested_the_free_crc_effort_on_its_pacific_date_and_vessel(self):
        effort, name, text = self.an_effort_and_a_file()
        [info] = self.preview(file_of(name, text))
        self.assertEqual((info["date"], info["vessel"], info["points"]),
                         (f"{effort.effort_date:%Y-%m-%d}", effort.vessel.code, 4))
        self.assertEqual(info["best"], effort.legacy_daily_effort_id)
        self.assertIn(effort.legacy_daily_effort_id, [e["id"] for e in info["efforts"]])

    def test_the_date_is_the_first_points_pacific_date_not_its_utc_date(self):
        effort = an_effort_with_no_track()
        # 03:00 UTC the next day is the evening of the Effort's day on the coast.
        text = gps_text(f"{effort.effort_date + datetime.timedelta(days=1):%Y-%m-%d} 03:00:00")
        [info] = self.preview(file_of(f"{effort.effort_date:%Y%m%d}-{effort.vessel.code}-late.csv", text))
        self.assertEqual(info["date"], f"{effort.effort_date:%Y-%m-%d}")

    def test_an_effort_that_has_a_track_is_not_suggested(self):
        effort = an_effort_with_one_track()
        text = gps_text(f"{effort.effort_date:%Y-%m-%d} 18:00:00")
        [info] = self.preview(file_of(f"{effort.effort_date:%Y%m%d}-ZZZ-x.csv", text))
        taken = [e for e in info["efforts"] if e["id"] == effort.legacy_daily_effort_id]
        self.assertTrue(taken and taken[0]["taken"])
        self.assertNotEqual(info["best"], effort.legacy_daily_effort_id)

    def test_a_file_with_no_rows_is_reported_not_suggested(self):
        [info] = self.preview(file_of("empty.csv", "datetime_utc,latitude,longitude\n"))
        self.assertEqual(info["points"], 0)
        self.assertIn("no usable GPS rows", info["error"])

    def test_importing_with_a_match_stores_the_file_creates_the_track_and_logs_it(self):
        effort, name, text = self.an_effort_and_a_file()
        data = self.client.post(f"{API}/import/", {
            "files": [file_of(name, text)],
            "choices": json.dumps({name: effort.legacy_daily_effort_id})}).json()

        self.assertTrue(data["ok"], data)
        track = Track.objects.get(daily_effort=effort)
        self.assertEqual((track.object_key, track.track_status, track.point_count), (name, "available", 4))
        self.assertEqual(data["done"][0]["id"], track.legacy_track_id)
        self.assertEqual(self.stored(name), text)
        self.assertEqual([e[1] for e in self.entries(track)], ["create"])
        self.assertEqual(geometry(name)[1], 4)

    def test_importing_without_a_match_makes_an_unmatched_track(self):
        effort, name, text = self.an_effort_and_a_file()
        data = self.client.post(f"{API}/import/", {
            "files": [file_of(name, text)], "choices": json.dumps({name: ""})}).json()
        self.assertTrue(data["ok"], data)
        track = Track.objects.get(object_key=name)
        self.assertEqual((track.daily_effort_id, track.track_status, track.survey_date),
                         (None, "unassociated", effort.effort_date))
        self.assertEqual(track.vessel.code, effort.vessel.code)
        self.assertEqual(self.get(f"{track.legacy_track_id}/").json()["state"], "unmatched")

    def test_a_second_file_for_the_same_effort_is_refused_and_leaves_nothing_behind(self):
        effort, name, text = self.an_effort_and_a_file()
        other = name.replace("from-unit", "second")
        files = self.bucket_files()
        data = self.client.post(f"{API}/import/", {
            "files": [file_of(name, text), file_of(other, text)],
            "choices": json.dumps({name: effort.legacy_daily_effort_id,
                                   other: effort.legacy_daily_effort_id})}).json()

        self.assertFalse(data["ok"])
        self.assertEqual([d["ok"] for d in data["done"]], [True, False])
        self.assertIn("already has a track file", data["done"][1]["message"])
        self.assertEqual(Track.objects.filter(daily_effort=effort).count(), 1)
        self.assertEqual(self.bucket_files() - files, {name})

    def test_importing_every_file_in_one_go_logs_each(self):
        effort, name, text = self.an_effort_and_a_file()
        data = self.client.post(f"{API}/import/", {
            "files": [file_of(name, text), file_of("20200101-ROB-loose.csv", text)],
            "choices": json.dumps({name: effort.legacy_daily_effort_id, "20200101-ROB-loose.csv": ""})}).json()
        self.assertTrue(data["ok"], data)
        loose = Track.objects.get(object_key="20200101-ROB-loose.csv")
        self.assertEqual(loose.survey_date.isoformat(), "2020-01-01")
        self.assertEqual([e[1] for e in self.entries(loose)], ["create"])

    def test_the_import_page_preselects_the_effort_it_was_opened_for(self):
        effort = an_effort_with_no_track()
        html = self.client.get(f"/cascadia-admin/tracks/import/?effort={effort.legacy_daily_effort_id}").content.decode()
        self.assertIn(f'WANTED = "{effort.legacy_daily_effort_id}"', html)
        self.assertIn("Import Track Files", html)
        self.assertIn("Include Efforts From Other Research Groups", html)


class SizeLimitTests(ManagerTest):
    """No upload is read past the limits: one file, and one import batch."""

    def small(self, file=100, batch=150):
        return mock.patch.multiple(tracks, MAX_FILE_BYTES=file, MAX_BATCH_BYTES=batch)

    def test_a_file_over_the_limit_is_refused_by_the_preview_and_the_import(self):
        effort = an_effort_with_no_track()
        name = f"{effort.effort_date:%Y%m%d}-{effort.vessel.code}-big.csv"
        files = self.bucket_files()
        with self.small(file=50):
            for path, data in (("import/preview/", {"files": [file_of(name, gps_text())]}),
                               ("import/", {"files": [file_of(name, gps_text())],
                                            "choices": json.dumps({name: effort.legacy_daily_effort_id})})):
                response = self.post(path, data)
                self.assertEqual(response.status_code, 400, path)
                self.assertIn("at most", response.json()["message"])
                self.assertIn("Nothing was changed", response.json()["message"])
        self.assertEqual(self.bucket_files(), files)
        self.assertFalse(Track.objects.filter(daily_effort=effort).exists())

    def test_a_batch_over_the_limit_is_refused_though_each_file_is_small(self):
        one, two = gps_text(count=2), gps_text(count=3)
        size = len(one.encode()) + len(two.encode())
        files = self.bucket_files()
        with self.small(file=size, batch=size - 1):
            data = {"files": [file_of("20200101-ROB-a.csv", one), file_of("20200102-ROB-b.csv", two)],
                    "choices": json.dumps({"20200101-ROB-a.csv": "", "20200102-ROB-b.csv": ""})}
            for path in ("import/preview/", "import/"):
                response = self.post(path, {"files": [file_of("20200101-ROB-a.csv", one),
                                                      file_of("20200102-ROB-b.csv", two)],
                                            "choices": data["choices"]})
                self.assertEqual(response.status_code, 400, path)
                self.assertIn("add up to", response.json()["message"])
        self.assertEqual(self.bucket_files(), files)

    def test_a_fill_file_over_the_limit_is_refused(self):
        track = a_matched_track()
        self.watch(track.object_key)
        with self.small(file=50):
            for path in ("fill/preview/", "fill/"):
                response = self.post(f"{track.legacy_track_id}/{path}", {"file": file_of("x.csv", gps_text())})
                self.assertEqual(response.status_code, 400, path)
                self.assertIn("at most", response.json()["message"])
        self.assertEqual(self.entries(track), [])

    def test_the_code_that_reads_an_upload_checks_too(self):
        with self.small(file=50):
            with self.assertRaisesRegex(ValueError, "at most"):
                tracks.add_file(self.user, file_of("20200101-ROB-a.csv", gps_text()))

    def test_a_save_over_the_limit_is_refused(self):
        track = a_matched_track()
        self.watch(track.object_key)
        with self.small(file=50):
            response = self.post(f"{track.legacy_track_id}/save/", {"text": gps_text(count=20)})
        self.assertEqual(response.status_code, 400)
        self.assertIn("at most", response.json()["message"])
        self.assertEqual(self.entries(track), [])

    def test_the_real_limits_are_a_sensible_size(self):
        self.assertEqual((tracks.MAX_FILE_BYTES, tracks.MAX_BATCH_BYTES), (25 * 1024 * 1024, 100 * 1024 * 1024))


class OneTrackPerEffortTests(ManagerTest):

    def test_a_file_cannot_be_matched_to_an_effort_that_has_one(self):
        effort = an_effort_with_one_track()
        track = an_unlinked_file()
        response = self.post(f"{track.legacy_track_id}/match/", {"effort": effort.legacy_daily_effort_id})
        self.assertEqual(response.status_code, 400)
        self.assertIn("already has a track file", response.json()["message"])
        self.assertIn("one track file at most", response.json()["message"])
        self.assertIsNone(Track.objects.get(pk=track.pk).daily_effort_id)
        self.assertEqual(self.entries(track), [])
        with self.assertRaisesRegex(ValueError, "already has a track file"):
            trackfix.link(self.user, track, effort)

    def test_a_file_cannot_be_added_for_an_effort_that_has_one(self):
        effort = an_effort_with_one_track()
        files = self.bucket_files()
        with self.assertRaisesRegex(ValueError, "already has a track file"):
            tracks.add_file(self.user, file_of("20200101-ROB-x.csv", gps_text()), effort=effort)
        self.assertEqual(self.bucket_files(), files)
        self.assertEqual(Track.objects.filter(daily_effort=effort).count(), 1)

    def test_an_import_with_a_match_to_an_effort_that_has_one_is_refused(self):
        effort = an_effort_with_one_track()
        data = self.client.post(f"{API}/import/", {
            "files": [file_of("20200102-ROB-x.csv", gps_text())],
            "choices": json.dumps({"20200102-ROB-x.csv": effort.legacy_daily_effort_id})}).json()
        self.assertFalse(data["ok"])
        self.assertIn("already has a track file", data["done"][0]["message"])
        self.assertFalse(Track.objects.filter(object_key="20200102-ROB-x.csv").exists())

    def test_none_of_the_31_efforts_with_more_than_one_can_gain_another(self):
        several = _several()
        self.assertEqual(len(several), 31)
        track = an_unlinked_file()
        for effort in several:
            with self.subTest(effort=effort.legacy_daily_effort_id):
                with self.assertRaises(ValueError):
                    trackfix.check_room(effort)
                with self.assertRaises(ValueError):
                    trackfix.link(self.user, track, effort)

    def test_their_tracks_may_still_be_edited_unmatched_and_deleted(self):
        effort = _several()[0]
        first, second, *_ = effort.tracks.order_by("legacy_track_id")
        self.watch(first.object_key)

        saved = self.post(f"{first.legacy_track_id}/save/", {"text": gps_text()}).json()
        self.assertTrue(saved["ok"], saved)
        self.assertTrue(self.post(f"{first.legacy_track_id}/unmatch/").json()["ok"])
        self.assertTrue(self.post(f"{second.legacy_track_id}/delete/").json()["ok"])
        self.assertEqual(effort.tracks.count(), 0)

    def test_matching_an_unmatched_file_to_a_free_effort_works_then_the_effort_is_full(self):
        effort = an_effort_with_no_track()
        track = an_unlinked_file()
        data = self.post(f"{track.legacy_track_id}/match/", {"effort": effort.legacy_daily_effort_id}).json()
        self.assertTrue(data["ok"], data)
        self.assertEqual(data["state"], "matched")
        self.assertEqual(data["effort"]["id"], effort.legacy_daily_effort_id)
        other = Track.objects.exclude(pk=track.pk).filter(daily_effort__isnull=True, point_count__gt=0).first()
        again = self.post(f"{other.legacy_track_id}/match/", {"effort": effort.legacy_daily_effort_id})
        self.assertEqual(again.status_code, 400)

    def test_an_unknown_effort_is_said_to_be_unknown(self):
        track = an_unlinked_file()
        response = self.post(f"{track.legacy_track_id}/match/", {"effort": "999999999"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("There is no Effort", response.json()["message"])


class AuditTests(ManagerTest):
    """Every change is in the Audit Log, and the ones it offers Undo for undo."""

    def undo(self, entry_id):
        return self.client.post(f"/cascadia-admin/audit/{entry_id}/", follow=True)

    def test_match_and_unmatch_are_entries_and_undo(self):
        effort = an_effort_with_no_track()
        track = an_unlinked_file()
        self.post(f"{track.legacy_track_id}/match/", {"effort": effort.legacy_daily_effort_id})
        self.post(f"{track.legacy_track_id}/unmatch/")
        entries = self.entries(track)
        self.assertEqual([e[1] for e in entries], ["associate", "dissociate"])

        self.undo(entries[1][0])
        self.assertEqual(Track.objects.get(pk=track.pk).daily_effort_id, effort.pk)
        self.undo(entries[0][0])
        self.assertIsNone(Track.objects.get(pk=track.pk).daily_effort_id)
        self.assertEqual(self.entries(track), [])

    def test_undoing_a_save_puts_the_earlier_text_and_numbers_back(self):
        track = a_matched_track()
        self.watch(track.object_key)
        before = self.stored(track.object_key)
        row = Track.objects.get(pk=track.pk)
        self.post(f"{track.legacy_track_id}/save/", {"text": gps_text(count=7)})
        [(entry_id, *_rest)] = self.entries(track)

        response = self.undo(entry_id)

        self.assertContains(response, "Undone")
        self.assertEqual(self.stored(track.object_key), before)
        again = Track.objects.get(pk=track.pk)
        self.assertEqual((again.point_count, again.length_nm, again.track_status),
                         (row.point_count, row.length_nm, row.track_status))
        self.assertEqual(geometry(track.object_key)[1], row.point_count)
        self.assertEqual(self.entries(track), [])
        # What was undone stays in _versions: nothing is ever lost.
        self.assertEqual(len(self.versions(track.object_key)), 2)

    def test_undoing_an_import_removes_the_track_and_its_file(self):
        effort = an_effort_with_no_track()
        name = f"{effort.effort_date:%Y%m%d}-{effort.vessel.code}-undo.csv"
        self.client.post(f"{API}/import/", {"files": [file_of(name, gps_text())],
                                            "choices": json.dumps({name: effort.legacy_daily_effort_id})})
        track = Track.objects.get(object_key=name)
        [(entry_id, *_rest)] = self.entries(track)

        self.undo(entry_id)

        self.assertFalse(Track.objects.filter(pk=track.pk).exists())
        self.assertNotIn(name, self.bucket_files())
        self.assertIsNone(geometry(name))

    def test_a_delete_keeps_the_file_in_deleted_and_the_row_in_the_log(self):
        track = a_matched_track()
        key = track.object_key
        before = self.stored(key)
        row = geometry(key)

        data = self.post(f"{track.legacy_track_id}/delete/").json()

        self.assertTrue(data["ok"], data)
        self.assertFalse(Track.objects.filter(pk=track.pk).exists())
        self.assertNotIn(key, self.bucket_files())
        [kept] = os.listdir(os.path.join(self.bucket, "_deleted", key))
        with open(os.path.join(self.bucket, "_deleted", key, kept)) as f:
            self.assertEqual(f.read(), before)
        self.assertIsNone(geometry(key))
        [(entry_id, action, *_rest)] = self.entries(track)
        self.assertEqual(action, "delete")
        snapshot = fetch_one("SELECT snapshot FROM app.audit_log WHERE id = %s", [entry_id])[0]
        snapshot = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
        self.assertEqual(snapshot["TrackT"][0]["TrackID"], track.legacy_track_id)
        self.assertEqual(snapshot["track_geometry"]["object_key"], key)
        # The pipeline has nothing to put a deleted track's file back under, so
        # the file is not a bucket file any more either.
        self.assertNotIn(key, track_objects.listing())

        # Undo from the Audit Log brings back the row, the line and the file.
        self.undo(entry_id)
        self.assertTrue(Track.objects.filter(pk=track.pk).exists())
        self.assertEqual(self.stored(key), before)
        self.assertEqual(geometry(key)[1:3], row[1:3])
        self.assertFalse(os.path.exists(os.path.join(self.bucket, "_deleted", key, kept)))

    def test_restore_brings_a_deleted_track_back_as_an_entry_of_its_own(self):
        track = a_matched_track()
        key = track.object_key
        before = self.stored(key)
        self.post(f"{track.legacy_track_id}/delete/")
        listed = self.client.get(f"{API}/files/", {"status": "deleted"}).json()
        self.assertEqual([f["id"] for f in listed["files"]], [track.legacy_track_id])
        opened = self.get(f"{track.legacy_track_id}/").json()
        self.assertEqual((opened["state"], opened["name"], opened["text"]), ("deleted", key, before))

        data = self.post(f"{track.legacy_track_id}/restore/").json()

        self.assertTrue(data["ok"], data)
        self.assertEqual(Track.objects.get(pk=track.pk).daily_effort_id, track.daily_effort_id)
        self.assertEqual(self.stored(key), before)
        entries = self.entries(track)
        self.assertEqual([e[1] for e in entries], ["delete", "restore"])
        restored_by = fetch_one("SELECT restored_by FROM app.audit_log WHERE id = %s", [entries[0][0]])[0]
        self.assertEqual(restored_by, entries[1][0])
        self.assertEqual(self.client.get(f"{API}/files/", {"status": "deleted"}).json()["files"], [])
        again = self.post(f"{track.legacy_track_id}/restore/")
        self.assertEqual(again.status_code, 400)

    def test_an_unmatch_cannot_be_undone_onto_an_effort_that_has_another_file_now(self):
        effort = an_effort_with_one_track()
        first = effort.tracks.get()
        self.post(f"{first.legacy_track_id}/unmatch/")
        other = Track.objects.exclude(pk=first.pk).filter(daily_effort__isnull=True, point_count__gt=0).first()
        self.assertTrue(self.post(f"{other.legacy_track_id}/match/", {"effort": effort.legacy_daily_effort_id}).json()["ok"])
        [(entry_id, *_rest)] = self.entries(first)

        response = self.undo(entry_id)

        self.assertContains(response, "has another track file now")
        self.assertEqual(list(effort.tracks.values_list("legacy_track_id", flat=True)), [other.legacy_track_id])
        self.assertEqual(len(self.entries(first)), 1)       # the entry is still there to undo later

    def test_a_deleted_track_cannot_be_restored_onto_an_effort_that_has_another_file_now(self):
        effort = an_effort_with_one_track()
        first = effort.tracks.get()
        self.post(f"{first.legacy_track_id}/delete/")
        other = Track.objects.filter(daily_effort__isnull=True, point_count__gt=0).first()
        self.post(f"{other.legacy_track_id}/match/", {"effort": effort.legacy_daily_effort_id})

        response = self.post(f"{first.legacy_track_id}/restore/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("has another track file now", response.json()["message"])
        self.assertFalse(Track.objects.filter(pk=first.pk).exists())
        [(entry_id, action, *_rest)] = self.entries(first)
        self.assertEqual(action, "delete")
        self.assertIn("has another track file now", self.undo(entry_id).content.decode())

    def test_an_effort_that_had_two_may_be_put_back_to_two(self):
        effort = _several()[0]
        first = effort.tracks.order_by("legacy_track_id").first()
        self.post(f"{first.legacy_track_id}/unmatch/")
        [(entry_id, *_rest)] = self.entries(first)
        self.assertContains(self.undo(entry_id), "Undone")
        self.assertEqual(effort.tracks.count(), 2)
        self.assertEqual(Track.objects.get(pk=first.pk).daily_effort_id, effort.pk)

    def test_a_restore_whose_file_cannot_move_changes_nothing(self):
        track = a_matched_track()
        key = track.object_key
        self.post(f"{track.legacy_track_id}/delete/")
        [kept] = os.listdir(os.path.join(self.bucket, "_deleted", key))

        with mock.patch.object(track_objects, "move", side_effect=OSError("disk full")):
            response = self.post(f"{track.legacy_track_id}/restore/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("nothing was changed", response.json()["message"])
        self.assertFalse(Track.objects.filter(pk=track.pk).exists())
        self.assertIsNone(geometry(key))
        self.assertTrue(os.path.exists(os.path.join(self.bucket, "_deleted", key, kept)))
        self.assertEqual([e[1] for e in self.entries(track)], ["delete"])
        self.assertIsNone(fetch_one("SELECT restored_by FROM app.audit_log WHERE id = %s",
                                    [self.entries(track)[0][0]])[0])
        # And once the disk is back, the same restore works.
        self.assertTrue(self.post(f"{track.legacy_track_id}/restore/").json()["ok"])
        self.assertTrue(Track.objects.filter(pk=track.pk).exists())

    def test_an_undo_whose_file_cannot_move_changes_nothing(self):
        track = a_matched_track()
        key = track.object_key
        self.post(f"{track.legacy_track_id}/delete/")
        [(entry_id, *_rest)] = self.entries(track)

        with mock.patch.object(track_objects, "move", side_effect=OSError("disk full")):
            response = self.undo(entry_id)

        self.assertContains(response, "nothing was changed")
        self.assertFalse(Track.objects.filter(pk=track.pk).exists())
        self.assertIsNone(geometry(key))
        self.assertEqual(len(self.entries(track)), 1)
        self.assertContains(self.undo(entry_id), "Undone")
        self.assertTrue(Track.objects.filter(pk=track.pk).exists())

    def test_a_file_two_tracks_share_stays_when_one_is_deleted(self):
        effort = _several()[0]
        names = {}
        for t in effort.tracks.all():
            names.setdefault(t.object_key.lower(), []).append(t)
        shared = next((ts for ts in names.values() if len(ts) > 1), None)
        self.assertIsNotNone(shared, "no Effort whose tracks share a file in the data")
        key = shared[0].object_key
        self.post(f"{shared[0].legacy_track_id}/delete/")
        self.assertIn(key, self.bucket_files())
        self.assertTrue(Track.objects.filter(pk=shared[1].pk).exists())
        self.assertFalse(os.path.isdir(os.path.join(self.bucket, "_deleted")))

    def test_the_audit_pages_name_the_new_action(self):
        track = a_matched_track()
        self.watch(track.object_key)
        self.post(f"{track.legacy_track_id}/save/", {"text": gps_text()})
        html = self.client.get("/cascadia-admin/audit/").content.decode()
        self.assertIn("Edited File", html)
        self.assertIn("action-edit_file", html)
        [(entry_id, *_rest)] = self.entries(track)
        page = self.client.get(f"/cascadia-admin/audit/{entry_id}/").content.decode()
        self.assertIn("Edited File", page)
        self.assertIn("Undo This Change", page)
        # Its Track File link goes to the Track File Manager.
        self.assertIn(f"/cascadia-admin/tracks/?open={track.legacy_track_id}", page)

    def test_no_text_says_a_file_came_from_db167(self):
        track = a_matched_track()
        self.watch(track.object_key)
        self.post(f"{track.legacy_track_id}/save/", {"text": gps_text()})
        self.post(f"{track.legacy_track_id}/delete/")
        self.post(f"{track.legacy_track_id}/restore/")
        with connection.cursor() as cur:
            cur.execute("SELECT comment FROM app.audit_log WHERE target_table = 'TrackT' AND target_pk = %s",
                        [str(track.legacy_track_id)])
            for (comment,) in cur.fetchall():
                self.assertNotIn("DB167", comment or "")


class EffortPageTests(PermissionTest):
    """Add, Edit and Delete from an Effort's own page, for those allowed."""

    def setUp(self):
        super().setUp()
        self.bucket = os.environ["SPACES_LOCAL_DIR"]
        self.before = set(os.listdir(self.bucket))

    def tearDown(self):
        for name in set(os.listdir(self.bucket)) - self.before:
            path = os.path.join(self.bucket, name)
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)

    def test_a_manager_sees_the_file_as_a_link_with_edit_and_delete(self):
        sign_in(self.client, "manager", "Data Manager")
        effort = an_effort_with_one_track()
        track = effort.tracks.get()
        html = self.client.get(f"/efforts/{effort.legacy_daily_effort_id}/").content.decode()
        self.assertIn(f'href="/cascadia-admin/tracks/?open={track.legacy_track_id}"', html)
        self.assertEqual(html.count(f'href="/cascadia-admin/tracks/?open={track.legacy_track_id}"'), 2)
        self.assertIn(">Edit</a>", html)
        self.assertIn(f'action="/cascadia-admin/tracks/{track.legacy_track_id}/delete/"', html)
        self.assertNotIn("Add Track File", html)
        self.assertIn(">Change Track File</a>", html)
        self.assertIn(f'data-modal-url="/cascadia-admin/tracks/change/?effort={effort.legacy_daily_effort_id}'
                      f'&amp;track={track.legacy_track_id}"', html)
        self.assertNotIn("Choose Existing File", html)

    def test_an_effort_without_a_track_offers_add_track_file(self):
        sign_in(self.client, "manager", "Data Manager")
        effort = an_effort_with_no_track()
        html = self.client.get(f"/efforts/{effort.legacy_daily_effort_id}/").content.decode()
        self.assertIn(f'href="/cascadia-admin/tracks/?import_effort={effort.legacy_daily_effort_id}"', html)
        self.assertIn(">Add Track File</a>", html)
        self.assertIn(">Choose Existing File</a>", html)
        self.assertIn(f'data-modal-url="/cascadia-admin/tracks/change/?effort={effort.legacy_daily_effort_id}"', html)
        self.assertNotIn(">Change Track File</a>", html)

    def test_someone_without_the_permission_sees_none_of_it(self):
        sign_in(self.client, "viewer", "Viewer")
        for effort in (an_effort_with_one_track(), an_effort_with_no_track()):
            html = self.client.get(f"/efforts/{effort.legacy_daily_effort_id}/").content.decode()
            for gone in ("Add Track File", "Change Track File", "Choose Existing File", ">Edit</a>", "/delete/",
                         "/cascadia-admin/tracks/"):
                self.assertNotIn(gone, html, gone)

    def test_delete_from_the_effort_page_deletes_and_comes_back_to_the_effort(self):
        sign_in(self.client, "manager", "Data Manager")
        effort = an_effort_with_one_track()
        track = effort.tracks.get()

        response = self.client.post(f"/cascadia-admin/tracks/{track.legacy_track_id}/delete/", follow=True)

        self.assertEqual(response.redirect_chain[-1][0], f"/efforts/{effort.legacy_daily_effort_id}/")
        self.assertFalse(Track.objects.filter(pk=track.pk).exists())
        self.assertEqual([e[1] for e in audit_entries("TrackT", track.legacy_track_id)], ["delete"])
        self.assertContains(response, "deleted")

    def test_only_those_who_may_open_the_manager_can_delete(self):
        sign_in(self.client, "viewer", "Viewer")
        track = an_effort_with_one_track().tracks.get()
        self.assertEqual(self.client.post(f"/cascadia-admin/tracks/{track.legacy_track_id}/delete/").status_code, 403)
        self.assertTrue(Track.objects.filter(pk=track.pk).exists())
        # And not with a GET.
        self.client.logout()
        sign_in(self.client, "manager", "Data Manager")
        self.assertEqual(self.client.get(f"/cascadia-admin/tracks/{track.legacy_track_id}/delete/").status_code, 405)

    def test_the_manager_opens_the_file_or_the_import_named_in_the_address(self):
        sign_in(self.client, "manager", "Data Manager")
        track = an_effort_with_one_track().tracks.get()
        html = self.client.get(f"/cascadia-admin/tracks/?open={track.legacy_track_id}").content.decode()
        self.assertIn(f'data-open="{track.legacy_track_id}"', html)
        html = self.client.get("/cascadia-admin/tracks/?import_effort=27983").content.decode()
        self.assertIn('data-import-effort="27983"', html)


class PermissionTests(PermissionTest):

    def urls(self, track):
        i = track.legacy_track_id
        return {
            "get": ["/cascadia-admin/tracks/", "/cascadia-admin/tracks/import/", f"/cascadia-admin/tracks/{i}/fill/",
                    f"{API}/files/", f"{API}/{i}/", f"{API}/{i}/version/?key=x"],
            "post": [f"{API}/{i}/save/", f"{API}/{i}/fill/", f"{API}/{i}/fill/preview/", f"{API}/{i}/match/",
                     f"{API}/{i}/unmatch/", f"{API}/{i}/delete/", f"{API}/{i}/restore/", f"{API}/import/",
                     f"{API}/import/preview/", f"/cascadia-admin/tracks/{i}/delete/"],
        }

    def test_a_stranger_is_sent_to_sign_in(self):
        urls = self.urls(an_unlinked_file())
        for url in urls["get"]:
            self.assertEqual(self.client.get(url).status_code, 302, url)
        for url in urls["post"]:
            response = self.client.post(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn("/login/", response["Location"], url)

    def test_viewers_and_editors_are_refused_every_one(self):
        track = an_unlinked_file()
        for role in ("Viewer", "Editor"):
            self.client.logout()
            sign_in(self.client, role.lower(), role)
            urls = self.urls(track)
            for url in urls["get"]:
                self.assertEqual(self.client.get(url).status_code, 403, (role, url))
            for url in urls["post"]:
                self.assertEqual(self.client.post(url).status_code, 403, (role, url))
        self.assertTrue(Track.objects.filter(pk=track.pk).exists())

    def test_the_permission_to_open_data_health_is_enough_on_its_own(self):
        sign_in(self.client, "keeper", "Viewer", extra=["access_data_health"])
        track = an_unlinked_file()
        for url in self.urls(track)["get"][:5]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_the_old_pages_are_gone(self):
        sign_in(self.client, "manager", "Data Manager")
        for url in ("/cascadia-admin/tracks/effort/1/", "/cascadia-admin/tracks/file/1/"):
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_the_get_endpoints_refuse_a_post_and_the_other_way_round(self):
        sign_in(self.client, "manager", "Data Manager")
        i = an_unlinked_file().legacy_track_id
        self.assertEqual(self.client.post(f"{API}/files/").status_code, 405)
        self.assertEqual(self.client.get(f"{API}/{i}/save/").status_code, 405)
        self.assertEqual(self.client.get(f"{API}/import/").status_code, 405)


class BlankFileTests(WritePathTest):

    def run_command(self, *args):
        out = io.StringIO()
        call_command("create_blank_track_files", *args, stdout=out)
        return out.getvalue()

    def names_without_a_file(self):
        with connection.cursor() as cur:
            cur.execute('SELECT DISTINCT lower(file_name) FROM dbo."TrackT" WHERE file_name IS NOT NULL')
            wanted = {r[0] for r in cur.fetchall()}
        return wanted - {name.lower() for name in os.listdir(self.bucket)}

    def test_every_name_without_a_file_gets_a_header_only_file_and_a_pointless_line(self):
        missing = self.names_without_a_file()
        self.assertTrue(missing, "every track already has a file")

        out = self.run_command()

        self.assertIn(f"{len(missing):,} blank files made", out)
        self.assertEqual(self.names_without_a_file(), set())
        track = a_blank_track()
        with open(os.path.join(self.bucket, track.object_key)) as f:
            self.assertEqual(f.read(), "datetime_utc,latitude,longitude\n")
        parts, points, length, _etag = fetch_one(
            "SELECT ST_NumGeometries(geom), point_count, length_nm, etag FROM app.track_geometry "
            "WHERE object_key = %s", [track.object_key])
        self.assertEqual((parts, points, length), (None, 0, None))

    def test_a_dry_run_writes_nothing_and_a_second_run_makes_none(self):
        files = self.bucket_files()
        out = self.run_command("--dry-run")
        self.assertIn("would be made", out)
        self.assertEqual(self.bucket_files(), files)
        self.run_command()
        self.assertIn("0 blank files made", self.run_command())

    def test_a_file_already_in_the_bucket_is_never_touched(self):
        track = a_matched_track()
        self.watch(track.object_key)
        path = os.path.join(self.bucket, track.object_key)
        with open(path, "w") as f:
            f.write(CLEANED)
        self.run_command()
        with open(path) as f:
            self.assertEqual(f.read(), CLEANED)

    def test_a_blank_track_is_blank_in_the_data_and_has_no_missing_file_status(self):
        with connection.cursor() as cur:
            cur.execute("SELECT DISTINCT track_status FROM app.track ORDER BY 1")
            statuses = [r[0] for r in cur.fetchall()]
        self.assertIn("blank", statuses)
        self.assertNotIn("missing_file", statuses)


class ChangeTrackFileTests(ManagerTest):
    """Change Track File on an Effort's page: the files on offer, the swap
    as two Audit Log entries made together, and the one-track rule."""

    PAGE = "/cascadia-admin/tracks/change/"

    def setUp(self):
        super().setUp()
        self.effort = an_effort_with_one_track()
        self.old = self.effort.tracks.get()
        # Two files no Effort has: one on the Effort's date and Research Group, one on another day.
        spare = list(Track.objects.filter(daily_effort__isnull=True, point_count__gt=0)
                     .exclude(object_key__in=_shared_names()).order_by("legacy_track_id")[:2])
        self.same_day, self.other_day = spare
        with connection.cursor() as cur:
            cur.execute('UPDATE dbo."TrackT" SET "SurveyDate" = %s, "Research Group" = %s WHERE "TrackID" = %s',
                        [self.effort.effort_date, self.effort.research_group, self.same_day.legacy_track_id])
            cur.execute('UPDATE dbo."TrackT" SET "SurveyDate" = %s WHERE "TrackID" = %s',
                        [self.effort.effort_date + datetime.timedelta(days=40), self.other_day.legacy_track_id])
        self.number = self.effort.legacy_daily_effort_id

    def change(self, new, effort=None, old="same"):
        effort = effort or self.effort
        data = {"effort": effort.legacy_daily_effort_id, "new": new.legacy_track_id}
        if old == "same":
            old = self.old
        if old is not None:
            data["track"] = old.legacy_track_id
        return self.client.post(self.PAGE, data)

    def names(self, **params):
        data = self.client.get(f"{API}/candidates/", {"effort": self.number, **params}).json()
        self.assertTrue(data["ok"], data)
        return [f["name"] for f in data["files"]]

    def tracks_of(self, effort):
        return list(Track.objects.filter(daily_effort=effort).values_list("legacy_track_id", flat=True))

    # What is on offer

    def test_the_default_list_is_the_unmatched_files_on_the_efforts_date_and_group(self):
        names = self.names()
        self.assertIn(self.same_day.object_key, names)
        self.assertNotIn(self.other_day.object_key, names)
        self.assertNotIn(self.old.object_key, names)       # a matched file is never offered
        for f in self.client.get(f"{API}/candidates/", {"effort": self.number}).json()["files"]:
            self.assertIsNone(Track.objects.get(legacy_track_id=f["id"]).daily_effort_id)
            self.assertEqual(f["date"], self.effort.effort_date.isoformat())

    def test_a_file_imported_without_a_match_has_no_group_and_is_still_offered(self):
        with connection.cursor() as cur:
            cur.execute('UPDATE dbo."TrackT" SET "Research Group" = NULL WHERE "TrackID" = %s',
                        [self.same_day.legacy_track_id])
        self.assertIn(self.same_day.object_key, self.names())
        with connection.cursor() as cur:
            cur.execute('UPDATE dbo."TrackT" SET "Research Group" = %s WHERE "TrackID" = %s',
                        ["Some Other Group", self.same_day.legacy_track_id])
        self.assertNotIn(self.same_day.object_key, self.names(all_dates="1"))

    def test_show_all_dates_adds_the_other_days_and_the_search_narrows(self):
        everything = self.names(all_dates="1")
        self.assertIn(self.same_day.object_key, everything)
        self.assertIn(self.other_day.object_key, everything)
        self.assertEqual(self.names(all_dates="1", q=self.other_day.object_key.upper()), [self.other_day.object_key])
        self.assertEqual(self.names(q=self.other_day.object_key), [])      # not on the Effort's date

    def test_each_file_shows_what_the_pop_up_needs(self):
        row = [f for f in self.client.get(f"{API}/candidates/", {"effort": self.number}).json()["files"]
               if f["id"] == self.same_day.legacy_track_id][0]
        self.assertEqual(set(row), {"id", "name", "date", "vessel", "points", "length_nm", "same_vessel"})
        self.assertEqual(row["points"], self.same_day.point_count)

    def test_the_pop_up_names_the_effort_and_the_file_it_replaces(self):
        html = self.client.get(self.PAGE, {"effort": self.number, "track": self.old.legacy_track_id}).content.decode()
        self.assertIn("Change Track File", html)
        self.assertIn(self.old.object_key, html)
        self.assertIn('name="csrfmiddlewaretoken"', html)
        none = an_effort_with_no_track()
        html = self.client.get(self.PAGE, {"effort": none.legacy_daily_effort_id}).content.decode()
        self.assertIn("Choose Existing File", html)
        self.assertNotIn('name="track"', html)

    # The swap

    def test_changing_swaps_the_files_in_two_audit_entries_and_lands_on_the_effort(self):
        before = track_objects.get(self.old.object_key)
        response = self.change(self.same_day)
        self.assertRedirects(response, f"/efforts/{self.number}/", fetch_redirect_response=False)

        self.assertEqual(self.tracks_of(self.effort), [self.same_day.legacy_track_id])      # exactly one
        old = Track.objects.get(pk=self.old.pk)
        self.assertIsNone(old.daily_effort_id)
        self.assertEqual(old.track_status, "unassociated")
        self.assertEqual(track_objects.get(self.old.object_key), before)                    # its file is kept
        self.assertEqual(Track.objects.get(pk=self.same_day.pk).track_status, "available")
        first, second = self.entries(self.old), self.entries(self.same_day)
        self.assertEqual([e[1] for e in first][-1:], ["dissociate"])
        self.assertEqual([e[1] for e in second], ["associate"])
        self.assertEqual(first[-1][2], second[0][2])                                         # the same person
        self.assertLess(first[-1][0], second[0][0])                                          # dissociate, then associate
        self.assertEqual(second[0][3]["EffortID"]["new"], self.number)
        self.assertIn("now has", " ".join(m.message for m in get_messages(response.wsgi_request)))

    def test_each_step_can_be_undone_from_the_audit_log(self):
        self.change(self.same_day)
        old_entry, new_entry = self.entries(self.old)[-1][0], self.entries(self.same_day)[0][0]
        # The new file's match comes off first: the Effort cannot hold two.
        refused = self.client.post(f"/cascadia-admin/audit/{old_entry}/", follow=True)
        self.assertIn("another track file now", refused.content.decode())
        self.assertIsNone(Track.objects.get(pk=self.old.pk).daily_effort_id)
        self.client.post(f"/cascadia-admin/audit/{new_entry}/", follow=True)
        self.assertIsNone(Track.objects.get(pk=self.same_day.pk).daily_effort_id)
        self.client.post(f"/cascadia-admin/audit/{old_entry}/", follow=True)
        self.assertEqual(self.tracks_of(self.effort), [self.old.legacy_track_id])
        self.assertEqual(self.entries(self.same_day), [])

    def test_an_effort_with_no_file_is_given_the_chosen_one_in_one_entry(self):
        effort = an_effort_with_no_track()
        response = self.change(self.same_day, effort=effort, old=None)
        self.assertRedirects(response, f"/efforts/{effort.legacy_daily_effort_id}/", fetch_redirect_response=False)
        self.assertEqual(self.tracks_of(effort), [self.same_day.legacy_track_id])
        self.assertEqual([e[1] for e in self.entries(self.same_day)], ["associate"])

    def test_nothing_happens_if_the_second_step_fails(self):
        with mock.patch.object(trackfix, "_match", side_effect=ValueError("It broke.")):
            response = self.change(self.same_day)
        self.assertContains(response, "It broke.")                       # shown in the pop-up, which stays open
        self.assertEqual(self.tracks_of(self.effort), [self.old.legacy_track_id])
        self.assertEqual(self.entries(self.same_day), [])
        self.assertNotIn("dissociate", [e[1] for e in self.entries(self.old)])

    def test_a_file_an_effort_has_cannot_be_chosen(self):
        taken = Track.objects.filter(daily_effort__isnull=False).exclude(daily_effort=self.effort).first()
        response = self.change(taken)
        self.assertContains(response, "matched to an Effort already")
        self.assertEqual(self.tracks_of(self.effort), [self.old.legacy_track_id])
        self.assertEqual(Track.objects.get(pk=taken.pk).daily_effort_id, taken.daily_effort_id)

    def test_an_effort_that_has_a_file_is_not_given_a_second(self):
        response = self.change(self.same_day, old=None)
        self.assertContains(response, "already has a track file")
        self.assertEqual(self.tracks_of(self.effort), [self.old.legacy_track_id])

    def test_a_pop_up_left_open_after_the_file_changed_elsewhere_does_nothing(self):
        trackfix.unlink(self.user, self.old)
        response = self.change(self.same_day)
        self.assertRedirects(response, f"/efforts/{self.number}/", fetch_redirect_response=False)
        self.assertEqual(self.tracks_of(self.effort), [])
        self.assertEqual(self.entries(self.same_day), [])

    def test_an_unknown_choice_or_effort_is_said_so(self):
        response = self.client.post(self.PAGE, {"effort": self.number, "track": self.old.legacy_track_id, "new": ""})
        self.assertContains(response, "Choose a track file first.")
        self.assertEqual(self.client.post(self.PAGE, {"effort": "999999999", "new": 1}).status_code, 404)
        self.assertEqual(self.client.get(f"{API}/candidates/", {"effort": "999999999"}).status_code, 404)

    def test_an_address_or_a_post_that_is_not_a_whole_number_is_refused_not_an_error(self):
        for bad in ("abc", "1'", "1612'", "", "99999999999999999999", "²", "-1", "1.5"):
            with self.subTest(bad=bad):
                if bad:
                    self.assertEqual(self.client.get(self.PAGE, {"effort": self.number, "track": bad}).status_code, 404)
                    self.assertEqual(self.client.get(self.PAGE, {"effort": bad}).status_code, 404)
                    self.assertEqual(self.client.get(f"{API}/candidates/", {"effort": bad}).status_code, 404)
                    self.assertEqual(self.client.post(self.PAGE, {"effort": self.number, "track": bad,
                                                                  "new": self.same_day.legacy_track_id}).status_code, 404)
                    self.assertEqual(self.client.post(self.PAGE, {"effort": bad, "new": 1}).status_code, 404)
                response = self.client.post(self.PAGE, {"effort": self.number, "track": self.old.legacy_track_id,
                                                        "new": bad})
                self.assertContains(response, "Choose a track file first.")
        self.assertEqual(self.tracks_of(self.effort), [self.old.legacy_track_id])
        self.assertEqual(self.entries(self.same_day), [])

    def test_the_31_efforts_keep_the_number_of_files_they_have(self):
        effort = _several()[0]
        count = effort.tracks.count()
        first = effort.tracks.order_by("legacy_track_id").first()
        # A swap leaves the count as it was...
        response = self.client.post(self.PAGE, {"effort": effort.legacy_daily_effort_id,
                                                "track": first.legacy_track_id, "new": self.same_day.legacy_track_id})
        self.assertRedirects(response, f"/efforts/{effort.legacy_daily_effort_id}/", fetch_redirect_response=False)
        self.assertEqual(effort.tracks.count(), count)
        self.assertEqual(Track.objects.get(pk=self.same_day.pk).daily_effort_id, effort.pk)
        self.assertIsNone(Track.objects.get(pk=first.pk).daily_effort_id)
        # ...and choosing a file with none to replace still cannot add one.
        response = self.client.post(self.PAGE, {"effort": effort.legacy_daily_effort_id,
                                                "new": self.other_day.legacy_track_id})
        self.assertContains(response, "already has a track file")
        self.assertEqual(effort.tracks.count(), count)

    # Who may

    def test_only_those_who_may_open_the_manager_can_use_it(self):
        urls = [self.PAGE + f"?effort={self.number}", f"{API}/candidates/?effort={self.number}"]
        for role in ("Viewer", "Editor"):
            self.client.logout()
            sign_in(self.client, role.lower(), role)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 403, (role, url))
            self.assertEqual(self.change(self.same_day).status_code, 403, role)
        self.assertEqual(self.tracks_of(self.effort), [self.old.legacy_track_id])
        self.assertEqual(self.entries(self.same_day), [])
        self.client.logout()
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 302, url)
        self.assertEqual(self.change(self.same_day).status_code, 302)
        self.assertEqual(self.tracks_of(self.effort), [self.old.legacy_track_id])

    def test_a_post_without_the_csrf_token_is_refused(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        response = strict.post(self.PAGE, {"effort": self.number, "track": self.old.legacy_track_id,
                                           "new": self.same_day.legacy_track_id})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.tracks_of(self.effort), [self.old.legacy_track_id])

    def test_the_candidates_refuse_a_post_and_the_change_page_takes_a_get_and_a_post(self):
        self.assertEqual(self.client.post(f"{API}/candidates/", {"effort": self.number}).status_code, 405)
        self.assertEqual(self.client.get(self.PAGE, {"effort": self.number}).status_code, 200)


def _positioned():
    """Timeline rows that can be a point: a time and a position."""
    return EffortTimeline.objects.filter(at__isnull=False, lat__isnull=False, lon__isnull=False)


def efforts_with_positions():
    """The Efforts with no track file and two or more positioned rows."""
    enough = _positioned().order_by().values("daily_effort").annotate(n=Count("row_key")).filter(n__gte=2)
    return DailyEffort.objects.filter(tracks__isnull=True, effort_date__isnull=False,
                                      pk__in=enough.values("daily_effort")).select_related("vessel")


def an_effort_to_promote():
    """One whose draft has nothing wrong with it, so it can be saved as it stands."""
    for effort in efforts_with_positions().order_by("legacy_daily_effort_id")[:200]:
        if not tracks.line_errors(tracks.positions_text(trackfix.position_rows(effort))):
            return effort
    return None


def expected_text(effort):
    rows = [f"{r.at:%Y-%m-%d %H:%M:%S},{float(r.lat):.6f},{float(r.lon):.6f}"
            for r in _positioned().filter(daily_effort=effort).order_by("at", "row_key")]
    return "datetime_utc,latitude,longitude\n" + "\n".join(rows) + "\n"


class FromPositionsTests(ManagerTest):
    """The explorer's From Positions list, an Effort's draft, and Save As Track File."""

    def setUp(self):
        super().setUp()
        self.effort = an_effort_to_promote()
        if self.effort is None:
            self.skipTest("no Effort without a track has two recorded positions")
        self.number = self.effort.legacy_daily_effort_id

    def test_the_list_holds_only_efforts_with_no_track_and_two_positions(self):
        data = self.get("positions/").json()
        wanted = efforts_with_positions()
        self.assertEqual(data["total"], wanted.count())
        self.assertEqual(len(data["files"]), min(data["total"], data["cap"]))
        listed = [f["id"] for f in data["files"]]
        self.assertEqual(listed, [e.legacy_daily_effort_id for e in
                                  wanted.order_by("-effort_date", "-legacy_daily_effort_id")[:data["cap"]]])
        self.assertEqual(set(data["files"][0]), {"id", "date", "vessel", "group", "name", "state"})
        self.assertFalse(Track.objects.filter(daily_effort__legacy_daily_effort_id__in=listed).exists())

    def test_the_search_narrows_it_by_date_vessel_and_group(self):
        everything = self.get("positions/").json()["total"]
        effort = self.effort
        code = effort.vessel.code if effort.vessel else ""
        for word in (f"{effort.effort_date:%Y-%m}", code, effort.research_group):
            if not word:
                continue
            found = self.client.get(f"{API}/positions/", {"q": word}).json()
            self.assertLessEqual(found["total"], everything)
            self.assertTrue(found["files"], word)
            for f in found["files"]:
                self.assertIn(word.lower(), f"{f['date']} {f['vessel']} {f['group']}".lower())
        # Words together must all match: this one Effort's day, vessel and group.
        both = self.client.get(f"{API}/positions/", {
            "q": f"{effort.effort_date:%Y-%m-%d} {code} {effort.research_group or ''}"}).json()
        self.assertIn(self.number, [f["id"] for f in both["files"]])
        self.assertLess(both["total"], everything)
        self.assertEqual(self.client.get(f"{API}/positions/", {"q": "no such text anywhere"}).json()["total"], 0)

    def test_the_draft_is_the_positioned_rows_in_time_order(self):
        data = self.get(f"positions/{self.number}/").json()
        self.assertEqual(data["text"], expected_text(self.effort))
        self.assertTrue(data["draft"])
        self.assertEqual((data["effort"]["id"], data["state"]), (self.number, "draft"))
        self.assertEqual(data["name"], tracks.positions_key(self.effort))
        self.assertFalse(Track.objects.filter(daily_effort=self.effort).exists())

    def test_an_effort_that_has_a_track_has_no_draft(self):
        effort = an_effort_with_one_track()
        response = self.get(f"positions/{effort.legacy_daily_effort_id}/")
        self.assertEqual(response.status_code, 409)
        self.assertIn("already has a track file", response.json()["message"])
        self.assertEqual(self.get("positions/999999999/").status_code, 404)

    def test_saving_creates_the_track_and_a_second_save_is_refused(self):
        text = self.get(f"positions/{self.number}/").json()["text"]
        key = tracks.positions_key(self.effort)

        data = self.post(f"positions/{self.number}/save/", {"text": text}).json()

        self.assertTrue(data["ok"], data)
        track = Track.objects.get(daily_effort=self.effort)
        self.assertEqual((track.legacy_track_id, track.object_key), (data["id"], key))
        self.assertEqual(self.stored(key), tracks.process(text).cleaned)
        self.assertEqual(track.point_count, tracks.process(text).points)
        self.assertIsNotNone(geometry(key))
        self.assertEqual([e[1] for e in self.entries(track)], ["create"])
        self.assertEqual(audit_comment(track), "Created from the Effort's recorded positions "
                                               "(log entries, weather readings and sightings).")
        self.assertNotIn(self.number, [f["id"] for f in self.get("positions/").json()["files"]])

        again = self.post(f"positions/{self.number}/save/", {"text": text})
        self.assertFalse(again.json()["ok"])
        self.assertIn("already has a track file", again.json()["message"])
        self.assertEqual(Track.objects.filter(daily_effort=self.effort).count(), 1)

    def test_what_is_saved_is_the_text_sent_checked_again_on_the_server(self):
        text = self.get(f"positions/{self.number}/").json()["text"]
        files = self.bucket_files()
        bad = self.post(f"positions/{self.number}/save/", {"text": text + "not a row\n"}).json()
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["errors"][0][0], text.count("\n") + 1)
        empty = self.post(f"positions/{self.number}/save/", {"text": "datetime_utc,latitude,longitude\n"}).json()
        self.assertFalse(empty["ok"])
        self.assertFalse(Track.objects.filter(daily_effort=self.effort).exists())
        self.assertEqual(self.bucket_files(), files)

        edited = "\n".join(text.split("\n")[:-2]) + "\n"          # the last row taken out
        self.assertTrue(self.post(f"positions/{self.number}/save/", {"text": edited}).json()["ok"])
        track = Track.objects.get(daily_effort=self.effort)
        self.assertEqual(self.stored(track.object_key), tracks.process(edited).cleaned)

    def test_the_saved_track_is_an_ordinary_one(self):
        text = self.get(f"positions/{self.number}/").json()["text"]
        track_id = self.post(f"positions/{self.number}/save/", {"text": text}).json()["id"]
        opened = self.get(f"{track_id}/").json()
        self.assertEqual((opened["state"], opened["effort"]["id"]), ("matched", self.number))
        self.assertNotIn("draft", opened)

    def test_only_those_who_may_open_the_manager_can_use_it(self):
        text = self.get(f"positions/{self.number}/").json()["text"]
        for role in ("Viewer", "Editor"):
            self.client.logout()
            sign_in(self.client, role.lower(), role)
            self.assertEqual(self.get("positions/").status_code, 403, role)
            self.assertEqual(self.get(f"positions/{self.number}/").status_code, 403, role)
            self.assertEqual(self.post(f"positions/{self.number}/save/", {"text": text}).status_code, 403, role)
        self.assertFalse(Track.objects.filter(daily_effort=self.effort).exists())

    def test_the_page_offers_the_list_and_the_button(self):
        html = self.client.get("/cascadia-admin/tracks/").content.decode()
        for label in ("From Positions", "Save As Track File"):
            self.assertIn(label, html, label)
        page = self.client.get("/cascadia-admin/tracks/", {"positions_effort": self.number}).content.decode()
        self.assertIn(f'data-positions-effort="{self.number}"', page)


class PositionsButtonTests(PermissionTest):
    """Create Track From Positions on an Effort's page."""

    def page(self, effort):
        return self.client.get(f"/efforts/{effort.legacy_daily_effort_id}/").content.decode()

    def test_it_shows_for_an_effort_with_no_track_and_two_positions(self):
        effort = efforts_with_positions().first()
        if effort is None:
            self.skipTest("no Effort without a track has two recorded positions")
        sign_in(self.client, "manager", "Data Manager")
        html = self.page(effort)
        self.assertIn(f'href="/cascadia-admin/tracks/?positions_effort={effort.legacy_daily_effort_id}"', html)
        self.assertIn(">Create Track From Positions</a>", html)
        self.assertIn(">Add Track File</a>", html)

    def test_it_does_not_show_without_two_positions_or_with_a_track_or_without_the_permission(self):
        sign_in(self.client, "manager", "Data Manager")
        enough = efforts_with_positions().values("pk")
        few = (DailyEffort.objects.filter(tracks__isnull=True, effort_date__isnull=False)
               .exclude(pk__in=enough).first())
        for effort in (few, an_effort_with_one_track()):
            if effort is not None:
                self.assertNotIn("Create Track From Positions", self.page(effort))
        self.client.logout()
        sign_in(self.client, "viewer", "Viewer")
        effort = efforts_with_positions().first()
        if effort is not None:
            self.assertNotIn("Create Track From Positions", self.page(effort))


class DataCheckTests(ManagerTest):
    """Each file is checked whenever it is written (survey/track_checks.py), the
    explorer can list the files with a problem, and the open file shows what was found."""

    def a_track(self):
        """A matched track whose file is in the stand-in bucket now: an earlier test in the
        run may have moved another's away."""
        held = set(os.listdir(self.bucket))
        return next(t for t in (Track.objects.filter(daily_effort__isnull=False, track_status="available")
                                .exclude(object_key__in=_shared_names()).order_by("legacy_track_id"))
                    if t.object_key in held)

    def backwards_text(self):
        lines = gps_text(count=6).splitlines(keepends=True)
        return "".join(lines[:4] + [lines[2]] + lines[4:])   # line 5 is earlier than line 4

    def test_a_save_checks_the_file_and_the_track_health_filter_finds_it(self):
        track = self.a_track()
        self.watch(track.object_key)

        data = self.post(f"{track.legacy_track_id}/save/", {"text": self.backwards_text()}).json()

        self.assertTrue(data["ok"], data)
        [problem] = data["checks"]["problems"]
        self.assertEqual((problem["code"], problem["ranges"]), ("backwards", [[4, 5]]))

        def listed(health):
            return [r["id"] for r in self.client.get(f"{API}/files/", {"health": health, "q": track.object_key}).json()["files"]]
        self.assertEqual(listed("backwards"), [track.legacy_track_id])
        self.assertEqual((listed("speed"), listed("good")), ([], []))
        self.assertEqual(self.get(f"{track.legacy_track_id}/").json()["checks"]["problems"][0]["code"], "backwards")

        # Put right, and it is Good.
        self.post(f"{track.legacy_track_id}/save/", {"text": gps_text(count=6)})
        self.assertEqual((listed("backwards"), listed("good")), ([], [track.legacy_track_id]))

    def test_a_deleted_file_loses_its_check_and_a_restored_one_gets_it_back(self):
        track = self.a_track()
        self.watch(track.object_key)
        self.post(f"{track.legacy_track_id}/save/", {"text": self.backwards_text()})
        self.assertIsNotNone(track_checks.read(track.object_key))

        self.assertTrue(self.post(f"{track.legacy_track_id}/delete/").json()["ok"])
        self.assertIsNone(track_checks.read(track.object_key))

        self.assertTrue(self.post(f"{track.legacy_track_id}/restore/").json()["ok"])
        self.assertEqual(track_checks.read(track.object_key)["problems"][0]["code"], "backwards")

    def test_the_nightly_run_checks_every_file_and_removes_the_check_of_a_file_gone(self):
        gone = os.path.join(track_checks.folder(), "no-such-file.csv.json")
        os.makedirs(track_checks.folder(), exist_ok=True)
        with open(gone, "w") as f:
            f.write("{}")
        out = io.StringIO()
        call_command("check_track_files", stdout=out)
        self.assertFalse(os.path.exists(gone))
        some = self.a_track().object_key
        self.assertIsNotNone(track_checks.read(some))
        self.assertIn("unchanged since their last check", out.getvalue())
        # A second run reads nothing again.
        again = io.StringIO()
        call_command("check_track_files", stdout=again)
        self.assertIn("Checked 0 files", again.getvalue())
