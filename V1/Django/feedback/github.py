"""Turning feedback into a GitHub issue. Nothing here touches Django's models
or settings, so it can be tested without a database: the token and repository
are passed in, and the token is never put into a message or a log."""

import json
import urllib.error
import urllib.request

# The form's choices, each with the label it adds to the issue (None for none).
TYPES = [
    ("Bug", "bug"),
    ("Feature Request", "enhancement"),
    ("Data Problem", "data problem"),
    ("Question", "question"),
    ("Other", None),
]
AREAS = [
    ("Explore", "area: explore"),
    ("Efforts", "area: efforts"),
    ("Sightings", "area: sightings"),
    ("Export Tool", "area: export tool"),
    ("Track File Manager", "area: track file manager"),
    ("Cascadia Admin", "area: cascadia admin"),
    ("Sign In and Accounts", "area: sign in and accounts"),
    ("Other", None),
]

API = "https://api.github.com/repos/{repo}/issues"
TIMEOUT = 15


class GitHubError(Exception):
    """Carries a plain sentence for the person using the form."""


def build_labels(kind, area):
    labels = ["feedback"]
    for choices, picked in ((TYPES, kind), (AREAS, area)):
        label = dict(choices).get(picked)
        if label:
            labels.append(label)
    return labels


def build_body(details, picture_urls, sender):
    parts = []
    if details:
        parts.append(details)
    parts.extend(f"![Picture {n}]({url})" for n, url in enumerate(picture_urls, 1))
    parts.append(f"Sent by {sender} from the website feedback form.")
    return "\n\n".join(parts)


def create_issue(token, repo, title, body, labels):
    """Open the issue and return its number, or raise GitHubError."""
    request = urllib.request.Request(
        API.format(repo=repo),
        data=json.dumps({"title": title, "body": body, "labels": labels}).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "cascadia-feedback-form",
            "Content-Type": "application/json",
        })
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read())["number"]
    except urllib.error.HTTPError as error:
        raise GitHubError(f"GitHub refused the feedback (error {error.code}).") from None
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        raise GitHubError("GitHub could not be reached.") from None
