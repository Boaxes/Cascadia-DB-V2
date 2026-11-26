"""The Feedback page: GitHub is always mocked, so no test creates an issue."""

import re
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from feedback import github
from feedback.models import FeedbackPicture
from TESTS.test_permissions import sign_in

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


def upload(name="a.png", data=PNG):
    return SimpleUploadedFile(name, data)


@override_settings(GITHUB_FEEDBACK_TOKEN="test-token", GITHUB_FEEDBACK_REPO="Owner/Repo")
class FeedbackPageTests(TestCase):

    def test_the_menu_link_shows_for_a_viewer(self):
        sign_in(self.client, "vera", "Viewer")
        page = self.client.get("/explore/").content.decode()
        self.assertIn('href="/feedback/">Feedback</a>', page)
        self.assertLess(page.index(">Feedback</a>"), page.index(">Settings</a>"))

    def test_a_stranger_is_sent_to_sign_in(self):
        response = self.client.get("/feedback/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_the_form_has_the_fields_in_order(self):
        sign_in(self.client, "vera", "Viewer")
        page = self.client.get("/feedback/").content.decode()
        names = re.findall(r'name="(title|details|kind|area|pictures)"', page)
        self.assertEqual(names, ["title", "details", "kind", "area", "pictures"])

    @override_settings(GITHUB_FEEDBACK_TOKEN="")
    def test_with_no_token_there_is_no_form(self):
        sign_in(self.client, "vera", "Viewer")
        response = self.client.get("/feedback/")
        self.assertContains(response, "not set up yet")
        self.assertNotContains(response, "fb-title")
        with mock.patch("urllib.request.urlopen") as urlopen:
            self.client.post("/feedback/", {"title": "x"})
        urlopen.assert_not_called()

    def test_a_submission_stores_the_picture_and_opens_the_issue(self):
        user = sign_in(self.client, "vera", "Viewer")
        with mock.patch("feedback.views.github.create_issue", return_value=7) as create:
            response = self.client.post("/feedback/", {
                "title": "Map is blank", "details": "Nothing loads.",
                "kind": "Bug", "area": "Explore", "pictures": upload()})
        self.assertRedirects(response, "/feedback/", fetch_redirect_response=False)
        picture = FeedbackPicture.objects.get()
        token, repo, title, body, labels = create.call_args.args
        self.assertEqual((token, repo, title), ("test-token", "Owner/Repo", "Map is blank"))
        self.assertEqual(labels, ["feedback", "bug", "area: explore"])
        self.assertEqual(body, f"Nothing loads.\n\n"
                               f"![Picture 1](https://testserver/feedback/picture/{picture.token}.png)\n\n"
                               f"Sent by {user.get_full_name()} from the website feedback form.")
        self.assertContains(self.client.get("/feedback/"), "Feedback Sent. It is issue number 7.")

    def test_a_failed_call_keeps_the_text_and_removes_the_pictures(self):
        sign_in(self.client, "vera", "Viewer")
        with mock.patch("feedback.views.github.create_issue",
                        side_effect=github.GitHubError("GitHub could not be reached.")):
            response = self.client.post("/feedback/", {
                "title": "Keep me", "details": "And me", "kind": "Question",
                "pictures": upload()})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GitHub could not be reached.")
        self.assertContains(response, "Choose the pictures again")
        self.assertContains(response, 'value="Keep me"')
        self.assertContains(response, "And me")
        self.assertContains(response, '<option value="Question" selected>')
        self.assertEqual(FeedbackPicture.objects.count(), 0)

    def test_bad_pictures_are_refused_before_anything_is_stored_or_sent(self):
        sign_in(self.client, "vera", "Viewer")
        with mock.patch("feedback.views.github.create_issue") as create:
            for files in ([upload("evil.png", b"<svg onload=x>")],
                          [upload(f"{n}.png") for n in range(4)]):
                response = self.client.post("/feedback/", {"title": "T", "pictures": files})
                self.assertContains(response, "Choose the pictures again")
            with mock.patch("feedback.pictures.MAX_BYTES", 10):
                response = self.client.post("/feedback/", {"title": "T", "pictures": [upload()]})
                self.assertContains(response, "over 5 MB")
        create.assert_not_called()
        self.assertEqual(FeedbackPicture.objects.count(), 0)

    def test_a_title_is_required(self):
        sign_in(self.client, "vera", "Viewer")
        with mock.patch("feedback.views.github.create_issue") as create:
            response = self.client.post("/feedback/", {"title": "  "})
        self.assertContains(response, "Please give the feedback a title.")
        create.assert_not_called()


class PictureUrlTests(TestCase):

    def test_the_picture_is_served_without_signing_in(self):
        picture = FeedbackPicture.objects.create(content_type="image/png", data=PNG)
        response = self.client.get(f"/feedback/picture/{picture.token}.png")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, PNG)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn("max-age=31536000", response["Cache-Control"])

    def test_an_unknown_token_is_a_404(self):
        self.assertEqual(self.client.get("/feedback/picture/nope.png").status_code, 404)
