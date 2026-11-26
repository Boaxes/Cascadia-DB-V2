"""
Tests of the Server page of the Django admin (the one log and the graph), and of
everything that writes to the server event log: sign-ins, exports, changes to
the data, the Django admin, refusals, and the command the deploy calls.
"""

import io
import json
import os
import tempfile

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings

from datahealth import audit, console, events, serverhealth
from datahealth.models import ServerEvent, ServerSample
from TESTS.test_permissions import sign_in

PAGE, FEED = "/admin/server/", "/admin/server/feed.json"
NO_FILES = override_settings(SERVER_LOG_FILES={"nginx": os.path.join(tempfile.gettempdir(), "no-such-log-*.log")})


def last(category, event=None):
    rows = ServerEvent.objects.filter(category=category)
    return (rows.filter(event=event) if event else rows).order_by("-id").first()


class AccessTests(TestCase):

    def test_a_stranger_is_sent_to_sign_in(self):
        for url in (PAGE, FEED):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn("/login/", response["Location"], url)

    def test_only_the_admin_role_opens_it(self):
        for name, role in (("viewer", "Viewer"), ("editor", "Editor"), ("manager", "Data Manager")):
            sign_in(self.client, name, role)
            for url in (PAGE, FEED + "?cursor={}"):
                self.assertEqual(self.client.get(url).status_code, 403, f"{role} {url}")
        sign_in(self.client, "boss", "Admin")
        for url in (PAGE, FEED + "?cursor={}"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_it_is_linked_from_the_django_admin_and_not_from_cascadia_admin(self):
        sign_in(self.client, "boss", "Admin")
        self.assertIn(f'href="{PAGE}"', self.client.get("/admin/").content.decode())
        self.assertNotIn("/admin/server/", self.client.get("/cascadia-admin/").content.decode())


class PageTests(TestCase):

    def setUp(self):
        sign_in(self.client, "boss", "Admin")
        self.folder = tempfile.mkdtemp()
        self.log = os.path.join(self.folder, "access.log")
        self.files = override_settings(SERVER_LOG_FILES={"nginx": self.log})
        self.files.enable()
        self.addCleanup(self.files.disable)

    def write(self, text):
        with open(self.log, "a", encoding="utf-8", newline="") as handle:
            handle.write(text)

    def test_the_page_is_a_console_and_a_graph_and_nothing_else(self):
        html = self.client.get(PAGE).content.decode()
        for needed in ('id="console"', 'id="graph"', 'id="server-facts"', 'id="server-feed"', ">Advanced</button>"):
            self.assertIn(needed, html)
        for gone in ("<select", 'type="search"', "Needs Attention", "Download CSV", "Load Older"):
            self.assertNotIn(gone, html, gone)
        self.assertEqual(html.count("<button"), 2)       # Advanced, and Sign Out in the header

    def test_the_log_holds_events_and_log_files_together_in_time_order(self):
        events.record("export", "download", message="An Excel export.", occurred_at="2026-03-01 10:00:05")
        self.write('1.2.3.4 - - [01/Mar/2026:10:00:00 +0000] "GET /explore/ HTTP/1.1" 200 5\n'
                   '1.2.3.4 - - [01/Mar/2026:10:00:09 +0000] "GET /broken/ HTTP/1.1" 500 5\n')
        lines, _ = console.read()
        ours = [(line["t"][-2:], line["src"], line["lv"]) for line in lines if line["t"].startswith("2026-03-01")]
        self.assertEqual(ours, [("00", "nginx", "info"), ("05", "site", "info"), ("09", "nginx", "error")])
        export = next(line for line in lines if line["text"].startswith("export/download"))
        self.assertEqual(export["plain"], "Someone downloaded an export.")
        # A routine line of a system log is for Advanced only; its error is always shown.
        self.assertEqual([line["plain"] for line in lines if line["src"] == "nginx" and line["t"].startswith("2026-03-01")],
                         [None, 'nginx: 1.2.3.4 - - "GET /broken/ HTTP/1.1" 500 5'])

    def test_the_feed_returns_only_what_is_new_since_its_cursor(self):
        self.write('1.2.3.4 - - [01/Mar/2026:10:00:00 +0000] "GET /old/ HTTP/1.1" 200 5\n')
        _, cursor = console.read()
        first = json.loads(self.client.get(FEED, {"cursor": json.dumps(cursor)}).content)
        # Opening the feed is itself nothing new: no file lines, and no event but the page's own.
        self.assertEqual([line for line in first["lines"] if line["src"] == "nginx"], [])

        events.record("tracks", "check_recomputed", message="needle.csv was checked again.")
        self.write('1.2.3.4 - - [01/Mar/2026:10:00:07 +0000] "GET /new/ HTTP/1.1" 200 5\n')
        second = json.loads(self.client.get(FEED, {"cursor": json.dumps(first["cursor"])}).content)
        texts = [line["text"] for line in second["lines"]]
        self.assertIn('1.2.3.4 - - "GET /new/ HTTP/1.1" 200 5', texts)
        self.assertIn("tracks/check_recomputed needle.csv was checked again.", texts)
        self.assertFalse(any("/old/" in text for text in texts))
        self.assertEqual(len(second["now"]), 5)
        self.assertEqual(second["facts"][0][0], "Uptime")

    def test_the_feed_needs_a_cursor(self):
        self.assertEqual(self.client.get(FEED).status_code, 400)
        self.assertEqual(self.client.get(FEED + "?cursor=[1]").status_code, 400)

    def test_an_error_is_followed_by_its_traceback(self):
        events.record("error", "server_error", level="error", message="ValueError: no",
                      traceback="Traceback (most recent call last):\n  File x\nValueError: no")
        texts = [line["text"] for line in console.read()[0]]
        at = texts.index("error/server_error ValueError: no")
        self.assertEqual([line["plain"] for line in console.read()[0]][at:at + 2], ["Something went wrong on a page.", None])
        self.assertEqual(texts[at + 1:at + 4], ["    Traceback (most recent call last):", "      File x", "    ValueError: no"])


@NO_FILES
class SampleTests(TestCase):

    def test_a_reading_is_kept_once_a_minute_and_drawn(self):
        serverhealth._state["next"] = 0
        serverhealth.maybe_sample()
        serverhealth.maybe_sample()                 # within the minute: nothing more
        self.assertEqual(ServerSample.objects.count(), 1)
        serverhealth._state["next"] = 0
        serverhealth.maybe_sample()                 # another worker in the same minute: still one
        self.assertEqual(ServerSample.objects.count(), 1)
        [point] = serverhealth.samples()
        self.assertEqual(len(point), 5)
        self.assertIsNotNone(point[4])              # the database answered, so it has a response time

    def test_a_request_takes_the_reading(self):
        serverhealth._state["next"] = 0
        self.client.get("/login/")
        self.assertEqual(ServerSample.objects.count(), 1)

    def test_the_facts_name_the_database_and_the_last_deploy(self):
        events.record("deploy", "deployed", message="Deployed abc1234.")
        facts = dict(serverhealth.facts(serverhealth.reading()))
        self.assertTrue(facts["Database Response"].endswith(" ms"))
        self.assertTrue(facts["Last Deploy"].endswith(" UTC"))
        self.assertIn("Uptime", facts)


class WhatIsLoggedTests(TestCase):

    def test_signing_in_out_and_failing_to(self):
        User.objects.create_user("pat", password="right-horse-battery")
        self.client.post("/login/", {"username": "pat", "password": "wrong"}, REMOTE_ADDR="203.0.113.9")
        failed = last("auth")
        self.assertEqual((failed.event, failed.level, failed.actor), ("login_failed", "warning", "pat"))
        self.assertEqual(failed.ip_address, "203.0.113.9")
        self.assertTrue(failed.details["known_user"])
        self.assertNotIn("wrong", json.dumps(failed.details) + failed.message)

        self.client.post("/login/", {"username": "nobody", "password": "x"})
        self.assertFalse(last("auth").details["known_user"])

        self.client.post("/login/", {"username": "pat", "password": "right-horse-battery"})
        self.assertEqual(last("auth").event, "login")
        self.client.post("/logout/")
        self.assertEqual(last("auth").event, "logout")

    def test_a_refused_page_is_logged_with_who_asked(self):
        sign_in(self.client, "viewer", "Viewer")
        self.assertEqual(self.client.get("/cascadia-admin/").status_code, 403)
        entry = last("security", "access_denied")
        self.assertEqual((entry.actor, entry.path), ("Viewer Test", "/cascadia-admin/"))

    def test_a_change_to_the_data_is_logged_with_its_audit_entry(self):
        user = sign_in(self.client, "editor", "Editor")
        entry_id = audit.record(user, "associate", "TrackT", 1336, changes={"EffortID": {"old": None, "new": 5}})
        entry = last("audit", "associate")
        self.assertEqual(entry.details["audit_id"], entry_id)
        self.assertEqual((entry.actor, entry.details["table"], entry.details["record"]),
                         ("Editor Test", "TrackT", "1336"))

    def test_a_change_in_the_django_admin_is_logged(self):
        sign_in(self.client, "boss", "Admin")
        other = User.objects.create_user("someone")
        self.client.post(f"/admin/auth/user/{other.pk}/delete/", {"post": "yes"})
        entry = last("admin", "deleted")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.actor, "Boss Test")
        self.assertIn("someone", entry.message)

    def test_an_export_is_logged(self):
        sign_in(self.client, "manager", "Data Manager")
        self.client.post("/export/add/", {"kind": "efforts", "qs": "year=2024"})
        response = self.client.get("/export/download/", {"format": "csv", "sheet": ["efforts"]})
        self.assertEqual(response.status_code, 200)
        entry = last("export", "download")
        self.assertEqual((entry.actor, entry.details["format"], entry.details["sheets"]),
                         ("Manager Test", "csv", ["efforts"]))
        self.assertGreater(entry.details["size_bytes"], 0)

    def test_a_pipeline_run_is_copied_into_the_log_once(self):
        with connection.cursor() as cur:
            cur.execute("SELECT to_regclass('app.pipeline_run') IS NOT NULL")
            if not cur.fetchone()[0]:
                self.skipTest("This database has no app.pipeline_run.")
            cur.execute("""INSERT INTO app.pipeline_run (run_id, started_at, finished_at, result, tests_passed, tests_failed)
                           VALUES ('test-run-1', now() - interval '10 minutes', now(), 'tests failed', 12, 2)""")
        events.sync_pipeline_runs()
        self.assertEqual(events.sync_pipeline_runs(), 0)
        entry = ServerEvent.objects.get(category="pipeline", details__run_id="test-run-1")
        self.assertEqual((entry.event, entry.level, entry.details["tests_failed"]), ("failed", "error", 2))


class CommandTests(TestCase):

    def test_the_deploy_can_add_a_line(self):
        call_command("log_server_event", "deploy", "deployed", "--actor", "GitHub Actions",
                     "--message", "Deployed abc1234.", "--detail", "commit=abc1234", stdout=io.StringIO())
        entry = last("deploy", "deployed")
        self.assertEqual((entry.actor, entry.message, entry.details),
                         ("GitHub Actions", "Deployed abc1234.", {"commit": "abc1234"}))

    def test_a_deploy_names_who_pushed_what(self):
        import base64
        subject = "Fix the export's time zone; $(reboot)"
        call_command("log_server_event", "deploy", "deployed", "--detail", "commit=3f9c2ab71d", "--detail",
                     "pushed_by=Boaxes", "--detail-b64", "subject=" + base64.b64encode(subject.encode()).decode(),
                     stdout=io.StringIO())
        entry = last("deploy", "deployed")
        self.assertEqual(entry.details["subject"], subject)
        self.assertEqual(events.describe(entry), f"Boaxes pushed 3f9c2ab ({subject}). The website was deployed.")
        with self.assertRaises(CommandError):
            call_command("log_server_event", "deploy", "deployed", "--detail-b64", "subject=not base64!",
                         stdout=io.StringIO())

    def test_a_wrong_category_event_or_detail_is_refused(self):
        for arguments in (["nonsense", "deployed"], ["deploy", "Not A Slug"],
                          ["deploy", "deployed", "--detail", "no-equals"],
                          ["deploy", "deployed", "--detail", "message=x"]):
            with self.assertRaises(CommandError, msg=arguments):
                call_command("log_server_event", *arguments, stdout=io.StringIO())
        self.assertIsNone(last("deploy"))

    def test_pruning_removes_only_old_lines(self):
        import datetime
        from datahealth.models import utcnow
        old = events.record("server", "started", occurred_at=utcnow() - datetime.timedelta(days=400))
        new = events.record("server", "started")
        call_command("prune_server_events", stdout=io.StringIO())
        self.assertFalse(ServerEvent.objects.filter(pk=old.pk).exists())
        self.assertTrue(ServerEvent.objects.filter(pk=new.pk).exists())
