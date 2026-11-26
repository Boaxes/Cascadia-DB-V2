"""
Tests of the Cascadia Admin pages (the dashboard, and undo on the audit log
page), and of the Django admin, where users and their roles are managed.
"""

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Group, User
from django.db import connection

from datahealth import access, audit
from TESTS.test_permissions import PermissionTest, sign_in


class DashboardTests(PermissionTest):

    def test_the_dashboard_is_three_cards_and_nothing_else(self):
        sign_in(self.client, "manager", "Data Manager")
        html = self.client.get("/cascadia-admin/").content.decode()
        for url, title in (("/cascadia-admin/pipeline/", "Data Pipeline"),
                           ("/cascadia-admin/audit/", "Audit Log"),
                           ("/cascadia-admin/tracks/", "Track File Manager")):
            self.assertIn(f'<a class="admin-card" href="{url}">', html, url)
            self.assertIn(f"<h2>{title}</h2>", html, title)
        self.assertEqual(html.count('class="admin-card"'), 3)
        for gone in ("charts.js", "chart-data", "kpi", "Needs Attention", "Statistics"):
            self.assertNotIn(gone, html, gone)

    def test_the_nav_names_the_track_file_manager_and_has_no_users_page(self):
        sign_in(self.client, "boss", "Admin")
        html = self.client.get("/cascadia-admin/").content.decode()
        self.assertIn(">Track File Manager</a>", html)
        self.assertNotIn("/cascadia-admin/users/", html)
        self.assertEqual(self.client.get("/cascadia-admin/users/").status_code, 404)


class AuditPageTests(PermissionTest):

    def test_only_someone_who_can_edit_can_undo_in_cascadia_admin(self):
        sign_in(self.client, "keeper", "Viewer", extra=["access_data_health"])
        self.assertEqual(self.client.get("/cascadia-admin/audit/").status_code, 200)
        self.assertEqual(self.client.post("/cascadia-admin/audit/1/").status_code, 403)

    def test_a_match_names_its_fields_plainly_and_shows_the_efforts_number(self):
        with connection.cursor() as cur:
            cur.execute('SELECT id, "DailyEffortID" FROM dbo."DailyEffortT" ORDER BY "DailyEffortID" LIMIT 1')
            internal, number = cur.fetchone()
        entry = audit.record(None, "associate", "TrackT", 1336, changes={
            "EffortID": {"old": None, "new": number}, "track_status": {"old": "unassociated", "new": "available"},
            "daily_effort_id": {"old": None, "new": internal}})
        only_id = audit.record(None, "associate", "TrackT", 1337, changes={
            "daily_effort_id": {"old": None, "new": internal}})
        sign_in(self.client, "manager", "Data Manager")
        listing = self.client.get("/cascadia-admin/audit/").content.decode()
        page = self.client.get(f"/cascadia-admin/audit/{entry}/").content.decode()
        for html in (listing, page):
            self.assertIn("Track Status", html)
            self.assertNotIn("track_status", html)
            self.assertNotIn("daily_effort_id", html)
            self.assertNotIn(str(internal), html)
        self.assertIn(f"Effort: NULL to {number}", listing)
        self.assertIn(f"<strong>{number}</strong>", page)
        # An entry with only the internal id still shows the number.
        self.assertIn(f"<strong>{number}</strong>", self.client.get(f"/cascadia-admin/audit/{only_id}/").content.decode())

    def test_labels_are_in_title_case(self):
        sign_in(self.client, "manager", "Data Manager")
        html = self.client.get("/cascadia-admin/audit/").content.decode()
        for label in ("Record Number", "Record Type", "All Records", "All Changes",
                      "Apply Filters", "What Changed"):
            self.assertIn(label, html, label)
        for old in ("All records", "All changes"):
            self.assertNotIn(old, html, old)


class PipelinePageTests(PermissionTest):
    """The unmatched tracks on the Data Pipeline page are read from the
    database each time it loads, not from a file."""

    def setUp(self):
        super().setUp()
        sign_in(self.client, "manager", "Data Manager")

    def unmatch(self, track, effort):
        with connection.cursor() as cur:
            cur.execute('UPDATE dbo."TrackT" SET daily_effort_id = NULL, "EffortID" = %s WHERE "TrackID" = %s',
                        [effort, track])

    def track_section(self):
        html = self.client.get("/cascadia-admin/pipeline/").content.decode()
        return html.split("TrackT:")[1].split("</details>")[0]

    def test_a_track_that_now_names_a_removed_effort_is_listed_with_the_reason(self):
        with connection.cursor() as cur:
            cur.execute('SELECT "TrackID" FROM dbo."TrackT" WHERE daily_effort_id IS NOT NULL '
                        'AND "TrackID" <> 1336 ORDER BY "TrackID" DESC LIMIT 1')
            track = cur.fetchone()[0]
        self.assertNotIn(f"<td>{track}</td>", self.track_section())
        self.unmatch(track, 7777777)
        section = self.track_section()
        self.assertIn("Its effort (7777777) was removed from DB167; left unmatched, waiting to be matched", section)
        self.assertIn(f"<td>{track}</td>", section)

    def test_a_track_matched_to_an_effort_is_not_listed(self):
        with connection.cursor() as cur:
            cur.execute('SELECT count(*) FROM dbo."TrackT" WHERE daily_effort_id IS NULL AND "EffortID" IS NOT NULL')
            waiting = cur.fetchone()[0]
        self.assertEqual(self.track_section().count("was removed from DB167; left unmatched"), 1 if waiting else 0)


class DjangoAdminUserTests(PermissionTest):

    def setUp(self):
        super().setUp()
        self.me = sign_in(self.client, "boss", "Admin")
        self.editor = User.objects.create_user("an-editor")
        self.editor.groups.add(Group.objects.get(name="Editor"))
        self.viewer = User.objects.create_user("a-viewer")
        self.viewer.groups.add(Group.objects.get(name="Viewer"))

    def test_the_user_list_shows_each_role_as_a_column(self):
        html = self.client.get("/admin/auth/user/").content.decode()
        self.assertIn("column-role", html)
        self.assertIn('<td class="field-role">Editor</td>', html)
        self.assertIn('<td class="field-role">Viewer</td>', html)

    def test_the_user_list_filters_by_role(self):
        html = self.client.get("/admin/auth/user/?role=Editor").content.decode()
        self.assertIn("an-editor", html)
        self.assertNotIn("a-viewer", html)
        for role in access.ROLES:
            self.assertIn(f"?role={role.replace(' ', '+')}", html, role)

    def test_someone_holding_two_roles_is_filed_under_the_higher(self):
        self.viewer.groups.add(Group.objects.get(name="Editor"))
        html = self.client.get("/admin/auth/user/?role=Viewer").content.decode()
        self.assertNotIn("a-viewer", html)
        html = self.client.get("/admin/auth/user/?role=Editor").content.decode()
        self.assertIn("a-viewer", html)

    def test_a_role_changed_in_the_admin_is_logged(self):
        url = f"/admin/auth/user/{self.viewer.pk}/change/"
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {
            "username": "a-viewer", "first_name": "", "last_name": "", "email": "",
            "is_active": "on", "groups": [Group.objects.get(name="Editor").pk],
            "last_login_0": "", "last_login_1": "",
            "date_joined_0": "2026-01-01", "date_joined_1": "00:00:00",
        })
        self.assertEqual(response.status_code, 302, response.content.decode()[:2000])
        self.assertEqual(access.role_of(User.objects.get(pk=self.viewer.pk)), "Editor")
        entry = LogEntry.objects.filter(object_id=str(self.viewer.pk)).latest("action_time")
        self.assertEqual((entry.action_flag, entry.user_id), (CHANGE, self.me.pk))
        self.assertIn("Groups", entry.get_change_message())

    def test_groups_can_be_managed(self):
        self.assertEqual(self.codes("/admin/auth/group/", "/admin/auth/group/add/",
                                    "/admin/auth/user/add/"), [200, 200, 200])


class DjangoAdminLookTests(PermissionTest):

    def test_the_admin_wears_the_sites_header_and_colours(self):
        sign_in(self.client, "boss", "Admin")
        for url in ("/admin/", "/admin/auth/user/", f"/admin/auth/user/{User.objects.first().pk}/change/"):
            html = self.client.get(url).content.decode()
            self.assertIn('<header class="site-header">', html, url)
            self.assertIn("survey/app.css", html, url)
            self.assertIn("datahealth/admin.css", html, url)
            self.assertIn("<span>Django Admin</span>", html, url)
            self.assertNotIn("dark_mode.css", html, url)
            self.assertNotIn("Django administration", html, url)

    def test_a_stranger_is_sent_to_the_sites_sign_in(self):
        for url in ("/admin/", "/admin/auth/user/", "/admin/login/"):
            response = self.client.get(url, follow=True)
            self.assertTrue(response.redirect_chain[-1][0].startswith("/login/"), url)
            self.assertIn("Sign in to continue.", response.content.decode(), url)
