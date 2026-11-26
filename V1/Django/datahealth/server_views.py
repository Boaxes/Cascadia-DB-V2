"""
The Server page of the Django admin: one log of everything that happens on the
server (datahealth/console.py), and a graph of how the machine is doing with a
few facts beside it (datahealth/serverhealth.py). It only reads.

Routed by AccessAdminSite.get_urls (datahealth/sites.py), so the permission
that opens the Django admin, access_django_admin, guards it.
"""

import json
import time

from django.contrib import admin
from django.http import JsonResponse
from django.shortcuts import render

from . import console, events, serverhealth


def _now(found):
    return [int(time.time()), found["cpu"], found["memory"], found["disk"], found["database_ms"]]


def server(request):
    events.sync_pipeline_runs()
    lines, cursor = console.read()
    found = serverhealth.reading()
    return render(request, "datahealth/server.html", {
        **admin.site.each_context(request), "title": "Server",
        "feed": {"lines": lines, "cursor": cursor, "samples": serverhealth.samples(), "now": _now(found),
                 "facts": serverhealth.facts(found), "hours": serverhealth.GRAPH_HOURS},
    })


def server_feed(request):
    """What is new since the page last asked: lines of the log after its cursor, and
    the machine's figures now."""
    try:
        cursor = json.loads(request.GET.get("cursor", ""))
    except ValueError:
        cursor = None
    if not isinstance(cursor, dict):
        return JsonResponse({"error": "A cursor is needed."}, status=400)
    lines, cursor = console.read(cursor)
    found = serverhealth.reading()
    return JsonResponse({"lines": lines, "cursor": cursor, "now": _now(found), "facts": serverhealth.facts(found)})
