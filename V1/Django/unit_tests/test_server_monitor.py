"""The Server page's parts that need no database: the machine figures, reading log
files into the one log, and the event recorder's habit of never raising."""

import datetime
import os
import tempfile
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from datahealth import console, events, serverhealth, sysmetrics


class MachineTests(SimpleTestCase):

    def test_the_snapshot_has_every_figure(self):
        data = sysmetrics.snapshot([("Here", tempfile.gettempdir())], interval=0.01)
        for key in ("host", "cpu_count", "cpu_percent", "load", "memory", "uptime", "disks"):
            self.assertIn(key, data)
        self.assertEqual(data["disks"][0]["label"], "Here")
        if data["memory"]:
            self.assertGreater(data["memory"]["total"], 0)
            self.assertTrue(0 <= data["memory"]["percent"] <= 100)

    def test_two_folders_on_one_disk_are_one_line_and_a_missing_one_is_left_out(self):
        here = tempfile.gettempdir()
        found = sysmetrics.disks([("A", here), ("B", here), ("Gone", "/no/such/folder/anywhere")])
        self.assertEqual([d["label"] for d in found], ["A"])

    def test_sizes_and_spans_read_the_way_people_say_them(self):
        self.assertEqual(serverhealth.size_text(512), "512 B")
        self.assertEqual(serverhealth.size_text(1536), "1.5 KB")
        self.assertEqual(serverhealth.size_text(None), "Not Available")
        self.assertEqual(serverhealth.span_text(93784), "1 day 2 hours")
        self.assertEqual(serverhealth.span_text(61), "1 minute 1 second")
        self.assertEqual(serverhealth.span_text(0), "0 seconds")


class ParseTests(SimpleTestCase):

    def test_each_logs_own_time_is_read_and_taken_off_the_line(self):
        when = datetime.datetime(2026, 11, 20, 23, 29, 16)
        for text, rest in (
            ("2026-11-20 23:29:16.123 UTC [2211] ERROR:  deadlock detected", "[2211] ERROR:  deadlock detected"),
            ("2026/11/20 23:29:16 [error] 812#812: upstream closed", "[error] 812#812: upstream closed"),
            ("2026-11-20T23:29:16+00:00 host sshd[1]: Failed password", "host sshd[1]: Failed password"),
            ('1.2.3.4 - - [20/Nov/2026:23:29:16 +0000] "GET / HTTP/1.1" 200 5', '1.2.3.4 - - "GET / HTTP/1.1" 200 5'),
        ):
            with self.subTest(text=text):
                self.assertEqual(console.parse(text, None), (when, rest))

    def test_a_line_with_no_time_keeps_the_one_before(self):
        before = datetime.datetime(2026, 1, 2, 3, 4, 5)
        self.assertEqual(console.parse("    raise ValueError", before), (before, "    raise ValueError"))
        self.assertEqual(console.parse("9999-99-99 99:99:99 nonsense", before)[0], before)

    def test_levels(self):
        self.assertEqual(console._level('"GET / HTTP/1.1" 502 166'), "error")
        self.assertEqual(console._level('"GET /admin/ HTTP/1.1" 403 12'), "warning")
        self.assertEqual(console._level('"GET /nothing HTTP/1.1" 404 12'), "info")
        self.assertEqual(console._level("[2211] FATAL:  too many clients"), "error")
        self.assertEqual(console._level("[warn] buffered to a temporary file"), "warning")
        self.assertEqual(console._level("LOG:  checkpoint starting"), "info")


class FileTests(SimpleTestCase):
    """Reading a file by cursor. No event log here: these call the file reader itself."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.path = os.path.join(self.folder, "postgresql-16.log")

    def append(self, text):
        with open(self.path, "a", encoding="utf-8", newline="") as handle:
            handle.write(text)

    def test_a_poll_returns_only_what_was_written_since(self):
        self.append("2026-11-20 10:00:00 UTC [1] LOG:  one\n2026-11-20 10:00:01 UTC [1] LOG:  two\n")
        lines, where = console._file("postgres", os.path.join(self.folder, "postgresql-*.log"), None)
        self.assertEqual([line["text"] for line in lines], ["[1] LOG:  one", "[1] LOG:  two"])
        self.assertEqual(lines[0]["t"], "2026-11-20 10:00:00")
        self.assertEqual(lines[0]["src"], "postgres")

        self.assertEqual(console._file("postgres", self.path, where)[0], [])
        self.append("2026-11-20 10:00:02 UTC [1] ERROR:  three\n  DETAIL: more\n2026-11-20 10:00:03 UTC [1] LOG:  half")
        lines, where = console._file("postgres", self.path, where)
        # The line still being written waits for the next read; the detail keeps its error's time.
        self.assertEqual([(line["t"][-2:], line["lv"]) for line in lines], [("02", "error"), ("02", "info")])
        self.append(" a line\n")
        self.assertEqual(console._file("postgres", self.path, where)[0][0]["text"], "[1] LOG:  half a line")

    def test_a_rotated_file_is_read_from_its_start(self):
        self.append("2026-11-20 10:00:00 UTC [1] LOG:  " + "x" * 200 + "\n")
        _, where = console._file("postgres", self.path, None)
        os.remove(self.path)
        self.append("2026-11-21 00:00:00 UTC [1] LOG:  new file\n")
        lines, _ = console._file("postgres", self.path, where)
        self.assertEqual([line["text"] for line in lines], ["[1] LOG:  new file"])

    def test_a_missing_file_is_left_out(self):
        self.assertEqual(console._file("nginx", os.path.join(self.folder, "nothing-*.log"), None), ([], None))

    def test_a_cursor_cannot_name_a_file_or_carry_junk(self):
        with override_settings(SERVER_LOG_FILES={"postgres": self.path}):
            held = console._held({"e": "1; drop", "j": "$(reboot)", "f": {
                "postgres": [self.path, 12], "passwd": ["/etc/passwd", 0], "nginx": "x", "bad": [self.path, -5]}})
        self.assertEqual(held, {"e": 0, "f": {"postgres": [self.path, 12]}, "j": None})
        self.assertIsNone(console._held("nonsense"))
        self.assertEqual(console._held({"j": "s=ab12;i=3f;b=77;m=1;t=5;x=9"})["j"], "s=ab12;i=3f;b=77;m=1;t=5;x=9")


class RecordTests(SimpleTestCase):

    def test_recording_with_no_database_returns_none_and_does_not_raise(self):
        self.assertIsNone(events.record("auth", "login", message="nobody can store this"))

    def test_the_address_comes_from_the_last_forwarded_entry_behind_the_proxy(self):
        request = SimpleNamespace(META={"REMOTE_ADDR": "127.0.0.1", "HTTP_X_FORWARDED_FOR": "6.6.6.6, 203.0.113.9"})
        self.assertEqual(events._address(request), "203.0.113.9")

    def test_a_forwarded_header_is_ignored_when_the_request_did_not_come_through_the_proxy(self):
        request = SimpleNamespace(META={"REMOTE_ADDR": "198.51.100.4", "HTTP_X_FORWARDED_FOR": "6.6.6.6"})
        self.assertEqual(events._address(request), "198.51.100.4")

    def test_junk_in_the_header_is_not_kept(self):
        request = SimpleNamespace(META={"REMOTE_ADDR": "127.0.0.1", "HTTP_X_FORWARDED_FOR": "<script>"})
        self.assertEqual(events._address(request), "127.0.0.1")

    def test_event_names_are_short_lower_case_words(self):
        for good in ("deployed", "login_failed", "a1"):
            self.assertTrue(events.valid_slug(good), good)
        for bad in ("", "Deployed", "has space", "1st", "x" * 41, "a;b"):
            self.assertFalse(events.valid_slug(bad), bad)
