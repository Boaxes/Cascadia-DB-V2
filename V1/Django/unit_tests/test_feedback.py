"""Feedback to GitHub: the issue's labels and body, the picture checks, and the
API call with urlopen mocked, so nothing here ever reaches GitHub."""

import io
import json
import urllib.error
from unittest import mock

from django.test import SimpleTestCase

from feedback import github, pictures

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


class LabelTests(SimpleTestCase):

    def test_feedback_is_always_there(self):
        self.assertEqual(github.build_labels("", ""), ["feedback"])
        self.assertEqual(github.build_labels("Other", "Other"), ["feedback"])

    def test_every_type_and_area_has_its_label(self):
        kinds = {"Bug": "bug", "Feature Request": "enhancement",
                 "Data Problem": "data problem", "Question": "question"}
        for kind, label in kinds.items():
            self.assertEqual(github.build_labels(kind, ""), ["feedback", label])
        self.assertEqual(
            [github.build_labels("", area)[-1] for area, _ in github.AREAS[:-1]],
            ["area: explore", "area: efforts", "area: sightings", "area: export tool",
             "area: track file manager", "area: cascadia admin",
             "area: sign in and accounts"])

    def test_a_type_and_an_area_together(self):
        self.assertEqual(github.build_labels("Bug", "Explore"),
                         ["feedback", "bug", "area: explore"])

    def test_a_made_up_choice_adds_nothing(self):
        self.assertEqual(github.build_labels("bogus", "nowhere"), ["feedback"])


class BodyTests(SimpleTestCase):

    def test_details_then_pictures_then_the_sender(self):
        body = github.build_body("It broke.", ["https://x/a.png", "https://x/b.png"], "Ann Lee")
        self.assertEqual(body, "It broke.\n\n![Picture 1](https://x/a.png)\n\n"
                               "![Picture 2](https://x/b.png)\n\n"
                               "Sent by Ann Lee from the website feedback form.")

    def test_no_details_and_no_pictures_leaves_the_sender_line(self):
        self.assertEqual(github.build_body("", [], "ann"),
                         "Sent by ann from the website feedback form.")


class PictureTests(SimpleTestCase):

    def test_each_format_is_known_by_its_first_bytes(self):
        self.assertEqual(pictures.sniff(PNG), pictures.PNG)
        self.assertEqual(pictures.sniff(b"\xff\xd8\xff\xe0rest"), pictures.JPEG)
        self.assertEqual(pictures.sniff(b"GIF89a..."), pictures.GIF)
        self.assertEqual(pictures.sniff(b"GIF87a..."), pictures.GIF)
        self.assertEqual(pictures.sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 "), pictures.WEBP)

    def test_anything_else_is_refused(self):
        for data in (b"", b"<svg></svg>", b"%PDF-1.4", b"RIFF\x00\x00\x00\x00WAVEfmt ",
                     b"MZ\x90\x00"):
            self.assertIsNone(pictures.sniff(data))


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class CreateIssueTests(SimpleTestCase):

    def test_posts_to_the_repository_and_returns_the_number(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResponse(b'{"number": 42}')) as urlopen:
            number = github.create_issue("secret", "Owner/Repo", "T", "B", ["feedback", "bug"])
        self.assertEqual(number, 42)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.github.com/repos/Owner/Repo/issues")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data),
                         {"title": "T", "body": "B", "labels": ["feedback", "bug"]})
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertEqual(request.get_header("Accept"), "application/vnd.github+json")
        self.assertEqual(request.get_header("X-github-api-version"), "2022-11-28")
        self.assertTrue(request.get_header("User-agent"))
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 15)

    def test_a_refusal_becomes_a_plain_error_without_the_token(self):
        refusal = urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO(b"{}"))
        with mock.patch("urllib.request.urlopen", side_effect=refusal):
            with self.assertRaises(github.GitHubError) as caught:
                github.create_issue("secret", "Owner/Repo", "T", "B", [])
        self.assertIn("401", str(caught.exception))
        self.assertNotIn("secret", str(caught.exception))

    def test_an_unreachable_github_becomes_a_plain_error(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            with self.assertRaises(github.GitHubError):
                github.create_issue("secret", "Owner/Repo", "T", "B", [])
