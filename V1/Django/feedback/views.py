from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from datahealth import events

from . import github, pictures
from .models import FeedbackPicture

MAX_TITLE = 200
MAX_DETAILS = 20000


@login_required
def feedback(request):
    context = {
        "section": "feedback",
        "types": [name for name, _ in github.TYPES],
        "areas": [name for name, _ in github.AREAS],
        "max_title": MAX_TITLE,
        "ready": bool(settings.GITHUB_FEEDBACK_TOKEN),
        "values": {},
    }
    if request.method == "POST" and context["ready"]:
        values = {key: request.POST.get(key, "").strip()
                  for key in ("title", "details", "kind", "area")}
        context["values"] = values
        error = _send(request, values)
        if error is None:
            return redirect("feedback")
        messages.error(request, error)
    return render(request, "feedback/feedback.html", context)


def _send(request, values):
    """Open the issue. Returns a sentence describing what went wrong, or None."""
    if not values["title"]:
        return "Please give the feedback a title."
    if len(values["title"]) > MAX_TITLE:
        return f"The title can be at most {MAX_TITLE} characters."
    if len(values["details"]) > MAX_DETAILS:
        return f"The details can be at most {MAX_DETAILS:,} characters."

    files = request.FILES.getlist("pictures")
    if len(files) > pictures.MAX_FILES:
        return f"Please send at most {pictures.MAX_FILES} pictures. Choose the pictures again."
    checked = []
    for upload in files:
        if upload.size > pictures.MAX_BYTES:
            return f"{upload.name} is over 5 MB. Choose the pictures again."
        data = upload.read()
        kind = pictures.sniff(data)
        if kind is None:
            return f"{upload.name} is not a PNG, JPEG, GIF or WebP picture. Choose the pictures again."
        checked.append((kind, data))

    stored = [FeedbackPicture.objects.create(content_type=kind[0], data=data)
              for kind, data in checked]
    scheme = "http" if settings.DEBUG else "https"
    urls = [f"{scheme}://{request.get_host()}"
            + reverse("feedback_picture", args=[p.token, kind[1]])
            for p, (kind, _) in zip(stored, checked)]
    user = request.user
    body = github.build_body(values["details"], urls,
                             user.get_full_name() or user.get_username())
    try:
        number = github.create_issue(
            settings.GITHUB_FEEDBACK_TOKEN, settings.GITHUB_FEEDBACK_REPO,
            values["title"], body, github.build_labels(values["kind"], values["area"]))
    except github.GitHubError as error:
        FeedbackPicture.objects.filter(pk__in=[p.pk for p in stored]).delete()
        extra = " Choose the pictures again." if files else ""
        return f"{error} Nothing was sent.{extra}"
    events.record("feedback", "submitted", request=request, issue=number, kind=values.get("kind"),
                  area=values.get("area"), pictures=len(stored),
                  message=f"Feedback sent as GitHub issue {number}.")
    messages.success(request, f"Feedback Sent. It is issue number {number}.")
    return None


def picture(request, token, ext):
    """No sign-in: GitHub's image proxy fetches this. The token is the secret."""
    try:
        found = FeedbackPicture.objects.get(token=token)
    except FeedbackPicture.DoesNotExist:
        raise Http404
    response = HttpResponse(bytes(found.data), content_type=found.content_type)
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    return response
