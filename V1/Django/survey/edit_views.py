"""
Editing and deleting one record.

Both are two steps: fill in the form, then confirm what is about to happen.
The confirmation is the point -- it lists exactly which fields are changing and
what they are changing from, so nobody submits a form they misread, and it
takes an optional note that goes into the audit log beside the change.

Every write goes through admintools.audit, which is the one place that touches
the data, so nothing can be changed without being recorded.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import Http404
from django.shortcuts import redirect, render

from admintools import audit

from .editing import (FIELDS, changed, current, deletion_warning, display,
                      parse)
from .models import DailyEffort, Sighting, Species

RECORDS = {
    "sighting": {
        "table": "SightingT", "key": "SightingID",
        "model": Sighting, "lookup": "legacy_sighting_id",
        "label": "sighting", "url": "/sightings/%s/",
    },
    "daily_effort": {
        "table": "DailyEffortT", "key": "DailyEffortID",
        "model": DailyEffort, "lookup": "legacy_daily_effort_id",
        "label": "effort", "url": "/efforts/%s/",
    },
}


def _record(kind, pk):
    spec = RECORDS.get(kind)
    if spec is None:
        raise Http404(f"{kind} cannot be edited")
    try:
        obj = spec["model"].objects.get(**{spec["lookup"]: pk})
    except spec["model"].DoesNotExist:
        raise Http404(f"No {spec['label']} {pk}")
    return spec, obj


def _submitted(fields, post):
    return {f.column: parse(f, post.get(f.name)) for f in fields}


@login_required
def edit(request, kind, pk):
    spec, obj = _record(kind, pk)
    fields = FIELDS[kind]
    before = current(spec["table"], spec["key"], pk, fields)
    if before is None:
        raise Http404(f"No {spec['label']} {pk}")

    values = dict(before)
    pending = None

    if request.method == "POST":
        values = _submitted(fields, request.POST)
        pending = changed(before, values)

        if request.POST.get("confirmed") == "1":
            if not pending:
                messages.info(request, "Nothing was changed.")
                return redirect(spec["url"] % pk)
            # A coordinate edit redraws the point the map reads: dbo has a
            # trigger for that, so it happens wherever the write comes from.
            audit.update(request.user, kind, pk, pending,
                         comment=(request.POST.get("comment") or "").strip() or None)
            messages.success(
                request,
                f"{len(pending)} field{'' if len(pending) == 1 else 's'} changed. "
                "The change is in the audit log and can be undone from there.")
            return redirect(spec["url"] % pk)

        if not pending:
            messages.info(request, "Nothing was changed.")
            return redirect(spec["url"] % pk)

    # The confirmation reads better with labels than column names.
    labels = {f.column: f.label for f in fields}
    # Form controls need their own formats; the confirmation shows the values
    # as they will be stored.
    form_values = {f.column: display(f, values.get(f.column)) for f in fields}
    pending_rows = [
        {"label": labels.get(column, column),
         "old": before.get(column), "new": value}
        for column, value in (pending or {}).items()
    ]

    return render(request, "survey/edit.html", {
        "section": kind + "s" if kind == "sighting" else "efforts",
        "kind": kind,
        "label": spec["label"],
        "pk": pk,
        "object": obj,
        "fields": fields,
        "values": form_values,
        "before": before,
        "pending": pending,
        "pending_rows": pending_rows,
        "species_list": Species.objects.all(),
        "back": spec["url"] % pk,
        "comment": request.POST.get("comment", ""),
    })


@login_required
def delete(request, kind, pk):
    spec, obj = _record(kind, pk)
    with connection.cursor() as cur:
        cur.execute(f'SELECT 1 FROM dbo."{spec["table"]}" WHERE "{spec["key"]}" = %s',
                    [pk])
        if cur.fetchone() is None:
            raise Http404(f"No {spec['label']} {pk}")

    also = deletion_warning(spec["table"], spec["key"], pk)

    if request.method == "POST" and request.POST.get("confirmed") == "1":
        audit.delete(request.user, kind, pk,
                     comment=(request.POST.get("comment") or "").strip() or None)
        messages.success(
            request,
            f"{spec['label'].capitalize()} {pk} deleted. The whole record was "
            "kept, so it can be undone from the audit log.")
        return redirect("/sightings/" if kind == "sighting" else "/efforts/")

    return render(request, "survey/delete.html", {
        "section": "sightings" if kind == "sighting" else "efforts",
        "kind": kind,
        "label": spec["label"],
        "pk": pk,
        "object": obj,
        "also": also,
        "back": spec["url"] % pk,
    })
