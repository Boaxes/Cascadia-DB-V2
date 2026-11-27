"""Pages of the Survey group. Each is an empty landing page until Phase 5 builds it."""

from django.contrib.auth.decorators import permission_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


@permission_required("core.browse", raise_exception=True)
def explore(request: HttpRequest) -> HttpResponse:
    return render(request, "core/empty_page.html", {"title": "Explore"})


@permission_required("core.browse", raise_exception=True)
def effort_list(request: HttpRequest) -> HttpResponse:
    return render(request, "core/empty_page.html", {"title": "Efforts"})


@permission_required("core.browse", raise_exception=True)
def sighting_list(request: HttpRequest) -> HttpResponse:
    return render(request, "core/empty_page.html", {"title": "Sightings"})
