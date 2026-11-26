"""The Settings page: the colour profile, chosen there and kept in a cookie."""

from django.test import TestCase

from survey.services import COLOUR_PROFILE_COOKIE
from TESTS.test_permissions import sign_in


class SettingsPageTests(TestCase):

    def test_a_stranger_is_sent_to_sign_in(self):
        response = self.client.get("/settings/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_everyone_signed_in_finds_it_in_the_profile_menu(self):
        sign_in(self.client, "viewer", "Viewer")
        html = self.client.get("/explore/").content.decode()
        self.assertIn('<a href="/settings/">Settings</a>', html)
        html = self.client.get("/settings/").content.decode()
        self.assertIn("<h1>Settings</h1>", html)
        self.assertIn("Color Profile", html)
        # Cascadia until something else is chosen.
        self.assertIn('value="cascadia" checked', html)
        self.assertNotIn('value="generic" checked', html)

    def test_choosing_a_profile_keeps_it_and_every_page_uses_it(self):
        sign_in(self.client, "viewer", "Viewer")
        response = self.client.post("/settings/", {"colour_profile": "generic"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/settings/")
        cookie = response.cookies[COLOUR_PROFILE_COOKIE]
        self.assertEqual((cookie.value, cookie["path"]), ("generic", "/"))
        self.assertGreater(int(cookie["max-age"]), 300 * 24 * 3600)

        html = self.client.get("/settings/").content.decode()
        self.assertIn('value="generic" checked', html)
        self.assertIn("Settings saved.", html)
        html = self.client.get("/explore/").content.decode()
        self.assertIn('data-colour-profile="generic"', html)

    def test_an_unknown_profile_is_refused(self):
        sign_in(self.client, "viewer", "Viewer")
        response = self.client.post("/settings/", {"colour_profile": "neon"})
        self.assertNotIn(COLOUR_PROFILE_COOKIE, response.cookies)
        html = self.client.get("/settings/").content.decode()
        self.assertIn("Choose a color profile.", html)

    def test_the_filter_panel_no_longer_has_it(self):
        sign_in(self.client, "viewer", "Viewer")
        for url in ("/explore/", "/efforts/", "/sightings/"):
            html = self.client.get(url).content.decode()
            self.assertNotIn('id="colour-profile"', html, url)
            self.assertNotIn("Color Profile", html, url)
