"""The track bucket, through its local-folder stand-in."""

import hashlib
import io
import pathlib
import tempfile
from unittest import mock

from django.test import SimpleTestCase

from survey import track_objects


class LocalBucketTests(SimpleTestCase):

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = mock.patch.dict("os.environ", {"SPACES_LOCAL_DIR": folder.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_put_returns_the_etag_and_never_overwrites(self):
        self.assertEqual(track_objects.put("a.csv", b"one"), hashlib.md5(b"one").hexdigest())
        with self.assertRaises(FileExistsError):
            track_objects.put("a.csv", b"two")
        self.assertEqual(dict(track_objects.fetch(["a.csv"])), {"a.csv": b"one"})

    def test_a_key_cannot_climb_out_of_the_bucket(self):
        with self.assertRaises(ValueError):
            track_objects.put("../escape.csv", b"x")

    def test_fetch_skips_keys_the_bucket_does_not_hold_and_listing_skips_non_csv(self):
        track_objects.put("here.csv", b"x")
        track_objects.put("notes.txt", b"x")
        self.assertEqual([k for k, _ in track_objects.fetch(["gone.csv", "here.csv"])], ["here.csv"])
        self.assertEqual(list(track_objects.listing()), ["here.csv"])
        track_objects.delete("here.csv")
        track_objects.delete("here.csv")        # deleting twice is not an error
        self.assertEqual(list(track_objects.listing()), [])


class VersionTests(SimpleTestCase):
    """Replacing a file keeps the old one; deleting moves it; nothing is lost."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = mock.patch.dict("os.environ", {"SPACES_LOCAL_DIR": folder.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        track_objects.put("a.csv", b"one")

    def test_replace_keeps_the_old_file_under_versions(self):
        etag, kept = track_objects.replace("a.csv", "two")
        self.assertEqual(etag, hashlib.md5(b"two").hexdigest())
        self.assertRegex(kept, r"^_versions/a\.csv/\d{8}T\d{6}Z\.csv$")
        self.assertEqual(track_objects.get("a.csv"), b"two")
        self.assertEqual(track_objects.get(kept), b"one")
        self.assertEqual(track_objects.under("_versions/a.csv"), [kept])

    def test_two_replacements_in_one_second_keep_both_versions(self):
        track_objects.replace("a.csv", "two")
        track_objects.replace("a.csv", "three")
        self.assertEqual(len(track_objects.under("_versions/a.csv")), 2)
        self.assertEqual(track_objects.get("a.csv"), b"three")

    def test_put_still_refuses_to_overwrite(self):
        track_objects.replace("a.csv", "two")
        with self.assertRaises(FileExistsError):
            track_objects.put("a.csv", b"three")

    def test_replacing_a_file_that_is_not_there_is_an_error(self):
        with self.assertRaises(FileNotFoundError):
            track_objects.replace("missing.csv", "x")

    def test_retire_moves_the_file_to_deleted_and_never_removes_it(self):
        moved = track_objects.retire("a.csv")
        self.assertRegex(moved, r"^_deleted/a\.csv/\d{8}T\d{6}Z\.csv$")
        self.assertIsNone(track_objects.get("a.csv"))
        self.assertEqual(track_objects.get(moved), b"one")

    def test_listing_leaves_out_versions_and_deleted_files(self):
        track_objects.replace("a.csv", "two")
        track_objects.put("b.csv", b"x")
        track_objects.retire("b.csv")
        self.assertEqual(list(track_objects.listing()), ["a.csv"])


class PublicBucketTests(SimpleTestCase):

    def test_a_public_url_can_read_but_not_write(self):
        with mock.patch.dict("os.environ", {"SPACES_LOCAL_DIR": ""}), \
                mock.patch.object(track_objects, "BASE_URL", "https://example.test"), \
                mock.patch.object(track_objects, "ENDPOINT", ""):
            self.assertTrue(track_objects.configured())
            self.assertFalse(track_objects.can_write())
            with self.assertRaises(RuntimeError):
                track_objects.put("a.csv", b"x")


class FakeBucket:
    """The two calls download() makes, over a dict of key to bytes, two keys to a page."""

    def __init__(self, objects):
        self.objects, self.read = objects, []

    def list_objects_v2(self, Bucket, ContinuationToken=None):
        keys = sorted(self.objects)
        start = int(ContinuationToken or 0)
        page = {"Contents": [{"Key": k, "Size": len(self.objects[k]),
                              "ETag": '"%s"' % hashlib.md5(self.objects[k]).hexdigest()}
                             for k in keys[start:start + 2]],
                "IsTruncated": start + 2 < len(keys)}
        if page["IsTruncated"]:
            page["NextContinuationToken"] = str(start + 2)
        return page

    def get_object(self, Bucket, Key):
        self.read.append(Key)
        return {"Body": io.BytesIO(self.objects[Key])}


class DownloadTests(SimpleTestCase):
    """Copying the bucket into a folder that can stand in for it."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = pathlib.Path(folder.name)
        self.bucket = FakeBucket({
            "a.csv": b"one", "b.csv": b"two", "notes.txt": b"x", "test/c.csv": b"scratch",
            "_versions/a.csv/20260101T000000Z.csv": b"zero",
            "_deleted/d.csv/20260101T000000Z.csv": b"gone",
        })
        for patcher in (mock.patch.object(track_objects, "ENDPOINT", "https://example.test"),
                        mock.patch.object(track_objects, "KEY", "k"),
                        mock.patch.object(track_objects, "SECRET", "s"),
                        mock.patch.object(track_objects, "_client", lambda: self.bucket)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def files(self):
        return sorted(p.relative_to(self.folder).as_posix()
                      for p in self.folder.rglob("*") if p.is_file())

    def test_it_copies_the_gps_files_and_leaves_the_rest(self):
        self.assertEqual(track_objects.download(self.folder), (2, 0))
        self.assertEqual(self.files(), ["a.csv", "b.csv"])
        self.assertEqual((self.folder / "a.csv").read_bytes(), b"one")

    def test_all_brings_the_versions_and_the_deleted_files_too(self):
        self.assertEqual(track_objects.download(self.folder, everything=True), (4, 0))
        self.assertEqual(self.files(), ["_deleted/d.csv/20260101T000000Z.csv",
                                        "_versions/a.csv/20260101T000000Z.csv", "a.csv", "b.csv"])

    def test_a_second_run_fetches_only_what_changed(self):
        track_objects.download(self.folder)
        self.bucket.read.clear()
        self.bucket.objects["b.csv"] = b"new"
        self.assertEqual(track_objects.download(self.folder), (1, 1))
        self.assertEqual(self.bucket.read, ["b.csv"])
        self.assertEqual((self.folder / "b.csv").read_bytes(), b"new")

    def test_the_folder_then_stands_in_for_the_bucket(self):
        track_objects.download(self.folder)
        with mock.patch.dict("os.environ", {"SPACES_LOCAL_DIR": str(self.folder)}):
            self.assertEqual(list(track_objects.listing()), ["a.csv", "b.csv"])
            self.assertEqual(track_objects.get("a.csv"), b"one")

    def test_it_reads_the_real_bucket_even_where_a_local_folder_is_set(self):
        with mock.patch.dict("os.environ", {"SPACES_LOCAL_DIR": str(self.folder)}):
            self.assertEqual(track_objects.download(self.folder), (2, 0))

    def test_a_key_cannot_climb_out_of_the_folder(self):
        self.bucket.objects = {"_versions/../../escape.csv": b"x"}
        with self.assertRaises(ValueError):
            track_objects.download(self.folder, everything=True)

    def test_it_needs_a_key(self):
        with mock.patch.object(track_objects, "KEY", ""), self.assertRaises(RuntimeError):
            track_objects.download(self.folder)
