"""Who can do what: each role sees, and is allowed, exactly its own part."""

from django.contrib.auth.models import Group, User
from django.test import TestCase

from datahealth import access
from TESTS.test_write_paths import a_cleaned_sighting


def sign_in(client, username, role=None, extra=()):
    user = User.objects.create_user(username, first_name=username.title(), last_name="Test")
    access.ensure()
    if role:
        user.groups.add(Group.objects.get(name=role))
    if extra:
        user.user_permissions.set(access.permissions_named(extra))
    client.force_login(user)
    return user


class PermissionTest(TestCase):

    def setUp(self):
        self.pk, _ = a_cleaned_sighting()   # DB167's ID, which the address uses
        self.edit = f"/sightings/{self.pk}/edit/"
        self.delete = f"/sightings/{self.pk}/delete/"

    def codes(self, *urls):
        return [self.client.get(u).status_code for u in urls]


class RoleTests(PermissionTest):

    def test_a_stranger_is_sent_to_sign_in(self):
        for url in (self.edit, self.delete, "/export/", "/cascadia-admin/", "/admin/"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn("/login/", response["Location"], url)

    def test_a_viewer_can_look_and_nothing_else(self):
        sign_in(self.client, "viewer", "Viewer")
        self.assertEqual(self.codes(f"/sightings/{self.pk}/", "/explore/"), [200, 200])
        self.assertEqual(self.codes(self.edit, self.delete, "/export/", "/export/download/",
                                    "/cascadia-admin/", "/admin/"),
                         [403] * 6)

    def test_a_viewer_is_not_shown_what_they_cannot_use(self):
        sign_in(self.client, "viewer", "Viewer")
        html = self.client.get(f"/sightings/{self.pk}/").content.decode()
        for gone in ("/edit/", "/delete/", "Export", "Cascadia Admin", "Django Admin"):
            self.assertNotIn(gone, html, gone)
        self.assertIn("History", html)

    def test_an_editor_edits_and_deletes_but_does_not_export(self):
        sign_in(self.client, "editor", "Editor")
        self.assertEqual(self.codes(self.edit, self.delete), [200, 200])
        self.assertEqual(self.codes("/export/", "/cascadia-admin/", "/admin/"), [403] * 3)
        html = self.client.get(f"/sightings/{self.pk}/").content.decode()
        self.assertIn(self.edit, html)
        self.assertIn(self.delete, html)
        self.assertNotIn("Export", html)

    def test_edit_and_delete_can_be_granted_apart(self):
        sign_in(self.client, "onlyedit", "Viewer", extra=["edit_records"])
        self.assertEqual(self.codes(self.edit, self.delete), [200, 403])
        html = self.client.get(f"/sightings/{self.pk}/").content.decode()
        self.assertIn(self.edit, html)
        self.assertNotIn(self.delete, html)

    def test_a_data_manager_also_exports_and_opens_cascadia_admin(self):
        sign_in(self.client, "manager", "Data Manager")
        self.assertEqual(self.codes(self.edit, "/export/", "/cascadia-admin/"), [200, 200, 200])
        self.assertEqual(self.codes("/admin/"), [403])
        html = self.client.get("/explore/").content.decode()
        self.assertIn(">Export<", html)
        self.assertIn("Cascadia Admin", html)
        self.assertNotIn("Django Admin", html)

    def test_an_admin_opens_the_django_admin_where_records_are_read_only(self):
        sign_in(self.client, "boss", "Admin")
        self.assertEqual(self.codes("/admin/", "/admin/auth/user/", "/admin/auth/group/",
                                    "/admin/survey/sighting/", "/cascadia-admin/"),
                         [200] * 5)
        self.assertEqual(self.codes("/admin/survey/sighting/add/"), [403])
        self.assertEqual(self.codes(f"/admin/survey/sighting/{self.pk}/delete/"), [403])
        html = self.client.get("/admin/survey/sighting/").content.decode()
        self.assertNotIn("/admin/survey/sighting/add/", html)

    def test_the_django_admin_does_not_open_for_staff_alone(self):
        user = sign_in(self.client, "staffer", "Data Manager")
        user.is_staff = True
        user.save()
        self.assertEqual(self.codes("/admin/"), [403])


class SetupTests(PermissionTest):

    def test_users_without_a_role_are_placed_once(self):
        staff = User.objects.create_user("staff", is_staff=True)
        plain = User.objects.create_user("plain")
        access.ensure()
        self.assertEqual(access.role_of(staff), "Admin")
        self.assertEqual(access.role_of(plain), "Viewer")
        plain.groups.set(Group.objects.filter(name="Editor"))
        access.ensure()
        self.assertEqual(access.role_of(plain), "Editor")
