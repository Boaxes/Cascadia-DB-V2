"""
What Django itself announces, written to the event log: sign-ins, failed
sign-ins, sign-outs, changes made in the Django admin, and unhandled errors.

Connected once, from DataHealthConfig.ready. Every receiver goes through
events.record, which never raises, so none can break a sign-in or a page.
"""

import sys
import traceback

from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.core.signals import got_request_exception
from django.db.models.signals import post_save

from . import access, events

ADMIN_ACTIONS = {ADDITION: "added", CHANGE: "changed", DELETION: "deleted"}


def signed_in(sender, request, user, **kwargs):
    events.record("auth", "login", request=request, user=user,
                  message=f"{user.get_username()} signed in.", username=user.get_username(),
                  role=access.role_of(user) or ("Superuser" if user.is_superuser else None))


def signed_out(sender, request, user, **kwargs):
    # A sign-out with nobody signed in (the session had already ended) says nothing.
    if user is not None:
        events.record("auth", "logout", request=request, user=user,
                      message=f"{user.get_username()} signed out.", username=user.get_username())


def sign_in_failed(sender, credentials, request=None, **kwargs):
    # Only the name that was tried is kept. The password is never read.
    username = str(credentials.get("username", ""))[:150]
    known = get_user_model().objects.filter(**{get_user_model().USERNAME_FIELD: username}).exists() if username else False
    events.record("auth", "login_failed", request=request, actor=username,
                  message=f"Failed sign-in for {username or 'no name'}"
                          f"{'' if known else ' (no such user)'}.",
                  username=username, known_user=known)


def admin_change(sender, instance, created, **kwargs):
    if not created:
        return
    kind = ADMIN_ACTIONS.get(instance.action_flag, "changed")
    what = f"{instance.content_type} {instance.object_repr}" if instance.content_type_id else instance.object_repr
    events.record("admin", kind, user=instance.user,
                  message=f"{what}: {instance.get_change_message()}".strip(": "),
                  object=instance.object_repr, object_id=instance.object_id,
                  model=str(instance.content_type) if instance.content_type_id else None)


def request_failed(sender, request=None, **kwargs):
    kind, error, trace = sys.exc_info()
    if error is None:
        return
    events.record("error", "server_error", request=request, level="error",
                  message=f"{kind.__name__}: {error}"[:500], exception=kind.__name__,
                  method=getattr(request, "method", None),
                  traceback="".join(traceback.format_exception(kind, error, trace))[-6000:])


def connect():
    user_logged_in.connect(signed_in, dispatch_uid="serverlog_login")
    user_logged_out.connect(signed_out, dispatch_uid="serverlog_logout")
    user_login_failed.connect(sign_in_failed, dispatch_uid="serverlog_login_failed")
    post_save.connect(admin_change, sender=LogEntry, dispatch_uid="serverlog_admin")
    got_request_exception.connect(request_failed, dispatch_uid="serverlog_exception")
