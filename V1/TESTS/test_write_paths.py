"""
The website's write paths, each through the code the page itself calls: the
track tool's uploads and links, the edit and delete forms, and undo.

Each test runs in a transaction that is rolled back afterwards, so they don't
see each other's changes. The bucket is the test run's stand-in folder
(config/test_runner.py); each test removes any file it put there.
"""

import json
import os
import re
import shutil

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase
from unittest import mock

from datahealth import access, audit, trackfix
from datahealth.gps import tracks
from survey import history, track_objects
from survey.editing import FIELDS, current, display
from survey.models import DailyEffort, Track

# A GPS file as a logger writes one: a byte-order mark, Windows line endings,
# its own header names, times without seconds or with a one-digit hour, a
# point east of Greenwich and an impossible second, and a 45-minute silence
# that splits the line in two.
GPS_FILE = (
    "﻿DateTimeUTC,Latitude,Longitude\r\n"
    "2020-07-01 9:05,47.100000,-122.500000\r\n"
    "2020-07-01 09:06:00,47.101000,-122.501000\r\n"
    "2020-07-01 09:07:00,47.102000,-122.502000\r\n"
    "2020-07-01 09:08:00,47.103000,122.503000\r\n"      # east of Greenwich: dropped
    "2020-07-01 09:09:60,47.104000,-122.504000\r\n"     # second 60: dropped
    "2020-07-01 09:55:00,47.200000,-122.600000\r\n"     # after 46 minutes: a new line
    "2020-07-01 09:56:00,47.201000,-122.601000\r\n"
).encode("utf-8")

CLEANED = (
    "datetime_utc,latitude,longitude\n"
    "2020-07-01 09:05:00,47.100000,-122.500000\n"
    "2020-07-01 09:06:00,47.101000,-122.501000\n"
    "2020-07-01 09:07:00,47.102000,-122.502000\n"
    "2020-07-01 09:55:00,47.200000,-122.600000\n"
    "2020-07-01 09:56:00,47.201000,-122.601000\n"
)


def upload(name="GPS.csv"):
    return SimpleUploadedFile(name, GPS_FILE, content_type="text/csv")


def fetch_one(sql, params=()):
    with connection.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def audit_entries(table, pk):
    with connection.cursor() as cur:
        cur.execute("SELECT id, action, actor_name, changes FROM app.audit_log "
                    "WHERE target_table = %s AND target_pk = %s ORDER BY id", [table, str(pk)])
        # A raw cursor hands jsonb back as text (survey/history.py, _json).
        return [(i, action, actor, json.loads(changes) if isinstance(changes, str) else changes)
                for i, action, actor, changes in cur.fetchall()]


def geometry(key):
    return fetch_one("SELECT ST_NumGeometries(geom), point_count, length_nm, etag "
                     "FROM app.track_geometry WHERE object_key = %s", [key])


def an_effort_with_no_track():
    return (DailyEffort.objects
            .filter(research_group="CRC", effort_date__isnull=False, vessel__isnull=False, tracks__isnull=True)
            .order_by("legacy_daily_effort_id").first())


def audit_comment(track):
    """The note on the newest audit entry about a track."""
    return fetch_one("SELECT comment FROM app.audit_log WHERE target_table = 'TrackT' AND target_pk = %s "
                     "ORDER BY id DESC LIMIT 1", [str(track.legacy_track_id)])[0]


def an_unlinked_file():
    """A file with points that no Effort has."""
    return (Track.objects.filter(daily_effort__isnull=True, point_count__gt=0)
            .order_by("legacy_track_id").first())


class WritePathTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("tester", first_name="Test", last_name="Er")
        access.ensure()
        self.user.groups.add(Group.objects.get(name="Admin"))
        self.client.force_login(self.user)
        self.bucket = os.environ["SPACES_LOCAL_DIR"]
        self.files_before = set(os.listdir(self.bucket))
        self.kept = {}

    def tearDown(self):
        # What the test added, including the _versions and _deleted folders...
        for name in set(os.listdir(self.bucket)) - self.files_before:
            path = os.path.join(self.bucket, name)
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
        # ...and the files it changed in place, as they were.
        for name, body in self.kept.items():
            with open(os.path.join(self.bucket, name), "wb") as f:
                f.write(body)

    def watch(self, name):
        """A file this test will change in place: put back afterwards."""
        with open(os.path.join(self.bucket, name), "rb") as f:
            self.kept[name] = f.read()

    def bucket_files(self):
        return set(os.listdir(self.bucket))


class UploadTests(WritePathTest):

    def test_upload_for_an_effort_with_no_track(self):
        effort = an_effort_with_no_track()
        self.assertIsNotNone(effort, "no effort without a track to test with")

        _id, message = tracks.add_file(self.user, upload("my track.csv"), effort=effort)

        self.assertIn("5 points kept, 2 rows dropped", audit_comment(Track.objects.get(daily_effort=effort)))
        # Stored cleaned: UTF-8, no byte-order mark, LF line endings, one header.
        track = Track.objects.get(daily_effort=effort)
        stored = open(os.path.join(self.bucket, track.object_key), "rb").read()
        self.assertEqual(stored, CLEANED.encode("utf-8"))
        # Its line: two parts, split at the silence, with every kept point.
        parts, points, length, etag = geometry(track.object_key)
        self.assertEqual((parts, points), (2, 5))
        self.assertGreater(length, 0)
        self.assertEqual(etag, track_objects.listing()[track.object_key][1])
        code = effort.vessel.code
        self.assertEqual(track.object_key, f"{effort.effort_date:%Y%m%d}-{code}-my_track.csv")
        self.assertEqual((track.research_group, track.track_status, track.survey_date),
                         ("CRC", "available", effort.effort_date))
        self.assertIn("matched to effort", message)
        # One entry, under the importer's name.
        entries = audit_entries("TrackT", track.legacy_track_id)
        self.assertEqual([e[1:3] for e in entries], [("create", "Test Er")])

    def test_a_file_name_already_taken_is_refused(self):
        effort = an_effort_with_no_track()
        key = f"{effort.effort_date:%Y%m%d}-{effort.vessel.code}-GPS.csv"
        track_objects.put(key, b"datetime_utc,latitude,longitude\n")
        files = self.bucket_files()

        with self.assertRaisesRegex(ValueError, "already exists"):
            tracks.add_file(self.user, upload(), effort=effort)
        self.assertEqual(self.bucket_files(), files)
        self.assertFalse(Track.objects.filter(daily_effort=effort).exists())

    def test_a_failed_database_write_leaves_no_file(self):
        effort = an_effort_with_no_track()
        files = self.bucket_files()
        with mock.patch.object(tracks, "save_geometry", side_effect=RuntimeError("database down")):
            with self.assertRaises(RuntimeError):
                tracks.add_file(self.user, upload(), effort=effort)
        self.assertEqual(self.bucket_files(), files)
        self.assertFalse(Track.objects.filter(daily_effort=effort).exists())

    def test_regenerating_a_file_gives_the_line_its_upload_did(self):
        effort = an_effort_with_no_track()
        tracks.add_file(self.user, upload(), effort=effort)
        key = Track.objects.get(daily_effort=effort).object_key
        uploaded = fetch_one("SELECT geom::text, point_count, length_nm FROM app.track_geometry "
                             "WHERE object_key = %s", [key])

        outcome = tracks.regenerate(keys=[key])

        self.assertEqual(outcome["unchanged"], [key])
        self.assertEqual(fetch_one("SELECT geom::text, point_count, length_nm FROM app.track_geometry "
                                   "WHERE object_key = %s", [key]), uploaded)


class LinkTests(WritePathTest):

    def test_link_then_unlink(self):
        track = an_unlinked_file()
        effort = an_effort_with_no_track()

        trackfix.link(self.user, track, effort)
        linked = Track.objects.get(pk=track.pk)
        self.assertEqual((linked.daily_effort_id, linked.track_status), (effort.pk, "available"))

        trackfix.unlink(self.user, linked)
        unlinked = Track.objects.get(pk=track.pk)
        self.assertEqual((unlinked.daily_effort_id, unlinked.track_status), (None, "unassociated"))

        entries = audit_entries("TrackT", track.legacy_track_id)
        self.assertEqual([e[1] for e in entries], ["associate", "dissociate"])
        self.assertEqual(entries[0][3]["EffortID"], {"old": None, "new": effort.legacy_daily_effort_id})
        # The match is kept by the effort's hashed id, which survives DB167 renumbering it.
        self.assertEqual(entries[0][3]["daily_effort_id"], {"old": None, "new": effort.pk})


class UndoTests(WritePathTest):
    """Undo, as the audit log page does it."""

    def undo(self, entry_id):
        uploaded = audit.undo(entry_id)
        if uploaded:
            track_objects.delete(uploaded)
        self.assertIsNone(audit.entry(entry_id), "the entry should be gone from the log")

    def test_undoing_an_upload_for_an_effort_removes_the_record(self):
        effort = an_effort_with_no_track()
        tracks.add_file(self.user, upload(), effort=effort)
        track = Track.objects.get(daily_effort=effort)
        entry_id = audit_entries("TrackT", track.legacy_track_id)[0][0]

        self.undo(entry_id)

        self.assertFalse(Track.objects.filter(pk=track.pk).exists())
        self.assertNotIn(track.object_key, self.bucket_files())

    def test_undoing_a_link_unlinks(self):
        track = an_unlinked_file()
        effort = an_effort_with_no_track()
        trackfix.link(self.user, track, effort)

        self.undo(audit_entries("TrackT", track.legacy_track_id)[0][0])

        self.assertEqual(Track.objects.get(pk=track.pk).daily_effort_id, None)


def a_sighting_with_children():
    """A CRC sighting with samples, so a delete reaches further than itself:
    (DB167's ID, which its address uses; its hashed id, which dbo and the
    audit log use)."""
    return fetch_one("""
        SELECT s."SightingID", s.id FROM dbo."SightingT" s
        WHERE s."Research Group" = 'CRC'
          AND EXISTS (SELECT 1 FROM dbo."SampleT" c WHERE c.sighting_id = s.id)
          AND NOT EXISTS (SELECT 1 FROM app.audit_log a
                          WHERE a.target_table = 'SightingT' AND a.target_pk = s.id::text)
        ORDER BY 1 LIMIT 1""")


def a_cleaned_sighting():
    """A CRC sighting whose group type the spelling rule respelt, and which
    nobody has edited: (DB167's ID, its hashed id)."""
    return fetch_one("""
        SELECT d."SightingID", d.id FROM dbo."SightingT" d JOIN raw."SightingT" r USING ("SightingID")
        WHERE d."Research Group" = 'CRC' AND r."Group Type" <> d."Group Type"
          AND NOT EXISTS (SELECT 1 FROM app.audit_log a
                          WHERE a.target_table = 'SightingT' AND a.target_pk = d.id::text)
        ORDER BY 1 LIMIT 1""")


def post_edit(client, kind, table, legacy, pk, **changes):
    """Submit the edit form as a browser would: every field, as the form shows
    it, with the changed ones replaced, and the confirmation ticked. The form's
    address uses DB167's ID (legacy); the record is read by its hashed id."""
    fields = FIELDS[kind]
    before = current(table, "id", pk, fields)
    data = {f.name: display(f, before[f.column]) for f in fields}
    by_column = {f.column: f for f in fields}
    for column, value in changes.items():
        data[by_column[column].name] = value
    data["confirmed"] = "1"
    data["comment"] = "A test edit."
    url = {"sighting": "/sightings/%s/edit/", "daily_effort": "/efforts/%s/edit/"}[kind] % legacy
    return client.post(url, {k: "" if v is None else v for k, v in data.items()})


class EditAndDeleteTests(WritePathTest):

    def test_an_edit_changes_only_its_field_and_is_logged(self):
        legacy, pk = a_cleaned_sighting()
        before = fetch_one('SELECT to_jsonb(s) FROM dbo."SightingT" s WHERE id = %s', [pk])[0]

        response = post_edit(self.client, "sighting", "SightingT", legacy, pk, Comments="Edited in a test.")

        self.assertEqual(response.status_code, 302)
        after = fetch_one('SELECT to_jsonb(s) FROM dbo."SightingT" s WHERE id = %s', [pk])[0]
        before, after = (v if isinstance(v, dict) else json.loads(v) for v in (before, after))
        self.assertEqual({k for k in after if after[k] != before[k]}, {"Comments"})
        # The audit log names the record by its hashed id.
        [(_id, action, actor, changes)] = audit_entries("SightingT", pk)
        self.assertEqual((action, actor, changes["Comments"]["new"]),
                         ("update", "Test Er", "Edited in a test."))

    def test_a_delete_takes_the_record_and_its_children_and_undo_brings_them_back(self):
        legacy, pk = a_sighting_with_children()
        samples = fetch_one('SELECT count(*) FROM dbo."SampleT" WHERE sighting_id = %s', [pk])[0]

        response = self.client.post(f"/sightings/{legacy}/delete/", {"confirmed": "1"})

        self.assertEqual(response.status_code, 302)
        self.assertIsNone(fetch_one('SELECT 1 FROM dbo."SightingT" WHERE id = %s', [pk]))
        self.assertEqual(fetch_one('SELECT count(*) FROM dbo."SampleT" WHERE sighting_id = %s', [pk])[0], 0)

        [(entry_id, action, _actor, _changes)] = audit_entries("SightingT", pk)
        self.assertEqual(action, "delete")
        audit.undo(entry_id)
        self.assertIsNotNone(fetch_one('SELECT 1 FROM dbo."SightingT" WHERE id = %s', [pk]))
        self.assertEqual(fetch_one('SELECT count(*) FROM dbo."SampleT" WHERE sighting_id = %s', [pk])[0],
                         samples)


class HistoryTests(WritePathTest):

    def test_a_cleaned_then_edited_field_shows_every_step(self):
        legacy, pk = a_cleaned_sighting()
        original, cleaned = fetch_one(
            'SELECT r."Group Type", d."Group Type" FROM raw."SightingT" r '
            'JOIN dbo."SightingT" d USING ("SightingID") WHERE d.id = %s', [pk])

        post_edit(self.client, "sighting", "SightingT", legacy, pk, **{"Group Type": "Pod"})

        histories, _actions = history.record_history("sighting", pk)
        [group_type] = [h for h in histories if h.field == "Group Type"]
        self.assertEqual([(s.source, s.value) for s in group_type.steps],
                         [("original", original), ("rule", cleaned), ("edit", "Pod")])
        self.assertIn("Spelling", group_type.steps[1].detail)
        self.assertEqual(group_type.steps[2].actor, "Test Er")
        self.assertTrue(re.search(r"\S", group_type.steps[2].comment or ""))
