"""Pages of the Manage group. Each is an empty landing page until Phase 5 builds it."""

from django.contrib.auth.decorators import permission_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


@permission_required("core.manage_tracks", raise_exception=True)
def track_list(request: HttpRequest) -> HttpResponse:
    return render(request, "core/empty_page.html", {"title": "Track File Manager"})


@permission_required("core.manage_audit", raise_exception=True)
def audit_list(request: HttpRequest) -> HttpResponse:
    return render(request, "core/empty_page.html", {"title": "Audit Log"})


@permission_required("core.view_server", raise_exception=True)
def server_page(request: HttpRequest) -> HttpResponse:
    return render(request, "core/empty_page.html", {"title": "Server"})
