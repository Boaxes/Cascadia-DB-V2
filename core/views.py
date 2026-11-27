"""Pages that belong to no sidebar group: the home redirect, Settings and Feedback."""

from django.contrib.auth.decorators import permission_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render


def home(request: HttpRequest) -> HttpResponse:
    return redirect("survey:explore")


@permission_required("core.browse", raise_exception=True)
def settings_page(request: HttpRequest) -> HttpResponse:
    return render(request, "core/empty_page.html", {"title": "Settings"})


@permission_required("core.browse", raise_exception=True)
def feedback_page(request: HttpRequest) -> HttpResponse:
    return render(request, "core/empty_page.html", {"title": "Feedback"})
