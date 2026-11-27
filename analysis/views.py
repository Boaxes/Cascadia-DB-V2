"""Pages of the Data group. Each is an empty landing page until Phase 5 builds it."""

from django.contrib.auth.decorators import permission_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


@permission_required("core.browse", raise_exception=True)
def export_page(request: HttpRequest) -> HttpResponse:
    return render(request, "core/empty_page.html", {"title": "Export"})


@permission_required("core.browse", raise_exception=True)
def sql_page(request: HttpRequest) -> HttpResponse:
    return render(request, "core/empty_page.html", {"title": "SQL"})
