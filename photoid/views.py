"""Pages of the Photo-ID group. Each is an empty landing page until Phase 5 builds it."""

from django.contrib.auth.decorators import permission_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


@permission_required("core.browse", raise_exception=True)
def individual_list(request: HttpRequest) -> HttpResponse:
    return render(request, "core/empty_page.html", {"title": "Individuals"})
