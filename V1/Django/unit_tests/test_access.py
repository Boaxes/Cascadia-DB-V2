"""Who may do what: the role table and the view guard, with no database."""

from types import SimpleNamespace

from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, SimpleTestCase

from datahealth import access


def user(perms=(), active=True, authenticated=True, groups=()):
    return SimpleNamespace(
        is_active=active, is_authenticated=authenticated,
        has_perm=lambda name: name in {f"datahealth.{p}" for p in perms},
        groups=SimpleNamespace(all=lambda: [SimpleNamespace(name=g) for g in groups]))


class RoleTests(SimpleTestCase):

    def test_each_role_has_everything_the_one_before_has(self):
        order = ["Viewer", "Editor", "Data Manager", "Admin"]
        self.assertEqual(list(access.ROLES), order)
        for lower, higher in zip(order, order[1:]):
            with self.subTest(role=higher):
                self.assertLessEqual(set(access.ROLES[lower]), set(access.ROLES[higher]))

    def test_admin_holds_every_permission_and_no_role_names_an_unknown_one(self):
        self.assertEqual(set(access.ROLES["Admin"]), set(access.PERMISSIONS))
        for role, names in access.ROLES.items():
            with self.subTest(role=role):
                self.assertLessEqual(set(names), set(access.PERMISSIONS))

    def test_role_of_is_the_highest_group_held(self):
        self.assertEqual(access.role_of(user(groups=["Viewer", "Admin", "Editor"])), "Admin")
        self.assertEqual(access.role_of(user(groups=["Some other group"])), None)


class GuardTests(SimpleTestCase):

    def setUp(self):
        self.calls = []

        @access.require("export_data")
        def view(request):
            self.calls.append(request)
            return "ok"

        self.view = view

    def request(self, who):
        request = RequestFactory().get("/export/?a=1")
        request.user = who
        return request

    def test_a_stranger_is_sent_to_sign_in_and_brought_back(self):
        response = self.view(self.request(user(authenticated=False)))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/login/?next=/export/%3Fa%3D1")

    def test_someone_without_the_permission_is_refused(self):
        with self.assertRaises(PermissionDenied):
            self.view(self.request(user(perms=["edit_records"])))
        self.assertEqual(self.calls, [])

    def test_someone_with_the_permission_gets_the_view(self):
        self.assertEqual(self.view(self.request(user(perms=["export_data"]))), "ok")
