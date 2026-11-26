import secrets

from django.db import models


def new_token():
    return secrets.token_urlsafe(32)


class FeedbackPicture(models.Model):
    """A picture sent with feedback. GitHub cannot take an attachment through
    its API, so the site keeps the picture and the issue links to it. The
    address is the token alone: GitHub's image proxy has to fetch it without
    signing in, and nothing lists the tokens."""

    token = models.CharField(max_length=64, unique=True, default=new_token)
    content_type = models.CharField(max_length=40)
    data = models.BinaryField()
    created = models.DateTimeField(auto_now_add=True)
