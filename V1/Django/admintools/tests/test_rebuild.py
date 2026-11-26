"""
A change made on the website survives a rebuild.

The website writes dbo and the audit log. A rebuild throws dbo away and makes
it again from raw and the log, so every kind of change is made here through
the website, then the whole pipeline runs (dbt build, every test, the swap),
and each change must still be there. Then each is undone, the pipeline runs
again, and each must be gone.

These commit for real, because dbt connects separately and would not see a
change still inside a test's transaction. The test database is thrown away
after the run, so nothing is left behind.
"""

import os

from django.contrib.auth.models import User
from django.test import TransactionTestCase

from admintools import audit, trackfix
from admintools.gps import tracks
from survey.models import DailyEffort, Track

from . import rebuild
from .test_write_paths import (a_cleaned_sighting, a_missing_file, a_sighting_with_children,
                               an_effort_with_no_track, an_unlinked_file, audit_entries,
                               fetch_one, geometry, post_edit, upload)


def sighting(pk, column):
    row = fetch_one(f'SELECT "{column}" FROM dbo."SightingT" WHERE "SightingID" = %s', [pk])
    return row[0] if row else None


class SurvivesRebuildTests(TransactionTestCase):

    def test_every_kind_of_change_survives_a_rebuild_and_so_does_its_undo(self):
        user = User.objects.create_user("tester", first_name="Test", last_name="Er", is_staff=True)
        self.client.force_login(user)
        bucket = os.environ["SPACES_LOCAL_DIR"]

        # Every kind of change the website makes.
        missing = a_missing_file()
        tracks.add(user, upload(), track=missing)

        effort = an_effort_with_no_track()
        tracks.add(user, upload(), effort=effort)
        created = Track.objects.get(daily_effort=effort)

        unlinked = an_unlinked_file()
        target = DailyEffort.objects.filter(research_group="CRC").order_by("legacy_daily_effort_id").first()
        trackfix.link(user, unlinked, target)

        edited = a_cleaned_sighting()
        post_edit(self.client, "sighting", "SightingT", "SightingID", edited,
                  **{"Group Type": "Pod", "Start Dec Lat": "47.5", "Start Dec Long": "-122.5"})
        effort_edited = target.legacy_daily_effort_id
        post_edit(self.client, "daily_effort", "DailyEffortT", "DailyEffortID", effort_edited,
                  **{"Survey Comments": "Edited in a test."})

        deleted = a_sighting_with_children()
        samples = fetch_one('SELECT count(*) FROM dbo."SampleT" WHERE "SightingID" = %s', [deleted])[0]
        self.client.post(f"/sightings/{deleted}/delete/", {"confirmed": "1"})

        rebuild.build_and_swap()

        # The upload for a missing file: its line, and a status of available.
        again = Track.objects.get(legacy_track_id=missing.legacy_track_id)
        self.assertEqual((again.track_status, again.point_count), ("available", 5))
        self.assertEqual(again.geom.num_geom, 2)
        # The upload for an effort: the record, still linked, with its line.
        new = Track.objects.get(legacy_track_id=created.legacy_track_id)
        self.assertEqual((new.daily_effort_id, new.object_key, new.track_status, new.research_group),
                         (effort.pk, created.object_key, "available", "CRC"))
        self.assertEqual(new.point_count, 5)
        # The link.
        linked = Track.objects.get(legacy_track_id=unlinked.legacy_track_id)
        self.assertEqual((linked.daily_effort_id, linked.track_status), (target.pk, "available"))
        # The edits, and the point that follows the edited coordinates.
        self.assertEqual(sighting(edited, "Group Type"), "Pod")
        self.assertEqual(fetch_one('SELECT ST_Y(geom), ST_X(geom) FROM dbo."SightingT" '
                                   'WHERE "SightingID" = %s', [edited]), (47.5, -122.5))
        self.assertEqual(fetch_one('SELECT "Survey Comments" FROM dbo."DailyEffortT" '
                                   'WHERE "DailyEffortID" = %s', [effort_edited])[0], "Edited in a test.")
        # The delete, with the samples it took.
        self.assertIsNone(sighting(deleted, "SightingID"))
        self.assertEqual(fetch_one('SELECT count(*) FROM dbo."SampleT" WHERE "SightingID" = %s',
                                   [deleted])[0], 0)

        # Now undo each, newest first where one record has several, and rebuild.
        original_group_type = fetch_one('SELECT "Group Type" FROM raw."SightingT" '
                                        'WHERE "SightingID" = %s', [edited])[0]
        for table, pk in [("SightingT", deleted), ("DailyEffortT", effort_edited), ("SightingT", edited),
                          ("TrackT", unlinked.legacy_track_id), ("TrackT", created.legacy_track_id),
                          ("TrackT", missing.legacy_track_id)]:
            for entry_id, *_rest in reversed(audit_entries(table, pk)):
                uploaded = audit.undo(entry_id)
                if uploaded:
                    os.remove(os.path.join(bucket, uploaded))

        rebuild.build_and_swap()

        self.assertIsNone(geometry(missing.object_key))
        self.assertEqual(Track.objects.get(legacy_track_id=missing.legacy_track_id).track_status,
                         missing.track_status)
        self.assertFalse(Track.objects.filter(legacy_track_id=created.legacy_track_id).exists())
        self.assertIsNone(Track.objects.get(legacy_track_id=unlinked.legacy_track_id).daily_effort_id)
        # Back to what cleaning made of DB167's value, not to the raw value.
        self.assertNotEqual(sighting(edited, "Group Type"), "Pod")
        self.assertEqual(sighting(edited, "Group Type").lower(), original_group_type.strip().lower())
        self.assertEqual(sighting(deleted, "SightingID"), deleted)
        self.assertEqual(fetch_one('SELECT count(*) FROM dbo."SampleT" WHERE "SightingID" = %s',
                                   [deleted])[0], samples)
