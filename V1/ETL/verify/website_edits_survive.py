"""
Website edits survive a rebuild: run in the web container against a test
database, once with PHASE=make (an edit to a sighting and to an effort through
their forms, a track matched, a sighting deleted), then, after dbt build and
swap, with PHASE=check. The form edits cover every kind of field the forms
offer that the build works out itself: a sighting's species, calves and depth,
and an effort's distance. Part of ETL/verify/run_tests.sh.
"""
import json
import os
from django.contrib.auth.models import User
from django.db import connection
from django.test import Client
from datahealth import access, trackfix
from survey.editing import FIELDS, current, display
from survey.models import DailyEffort, Sighting, Track

PHASE = os.environ["PHASE"]
STATE = "/verify/reports/website_edits.json"

def one(sql, params=()):
    with connection.cursor() as cur:
        cur.execute(sql, params); return cur.fetchone()

if PHASE == "make":
    access.ensure()
    u, _ = User.objects.get_or_create(username="pipeline-check", defaults={"first_name": "Pipeline", "last_name": "Check"})
    u.is_superuser = True; u.save()
    c = Client(); c.force_login(u)
    # 1. A sighting's comment, species, calves and depth, through the edit form.
    s = Sighting.objects.filter(research_group="CRC").order_by("legacy_sighting_id")[10]
    fields = FIELDS["sighting"]; before = current("SightingT", "id", s.pk, fields)
    species = one('select min("SpeciesID") from dbo."SpeciesT" where "SpeciesID" is distinct from %s',
                  [before["species_id"]])[0]
    sighting_edits = {"Comments": "Edited before a rebuild.", "species_id": species, "num_calves": 7,
                      "depth_m": "123.45"}
    data = {f.name: display(f, before[f.column]) for f in fields}
    for f in fields:
        if f.column in sighting_edits:
            data[f.name] = sighting_edits[f.column]
    data.update(confirmed="1", comment="survive test")
    r = c.post(f"/sightings/{s.legacy_sighting_id}/edit/", {k: "" if v is None else v for k, v in data.items()})
    # 2. An effort's Locality and distance.
    e = DailyEffort.objects.filter(research_group="NB").order_by("legacy_daily_effort_id")[5]
    fields = FIELDS["daily_effort"]; before = current("DailyEffortT", "id", e.pk, fields)
    data = {f.name: display(f, before[f.column]) for f in fields}
    for f in fields:
        if f.column == "Locality":
            data[f.name] = "Locality Edited Before A Rebuild"
        if f.column == "total_distance_nm":
            data[f.name] = "42.125"
    data.update(confirmed="1")
    r2 = c.post(f"/efforts/{e.legacy_daily_effort_id}/edit/", {k: "" if v is None else v for k, v in data.items()})
    # 3. An unmatched track matched to an effort on its date (or any effort).
    t = Track.objects.filter(daily_effort__isnull=True, point_count__gt=0).order_by("legacy_track_id").first()
    free = DailyEffort.objects.filter(tracks__isnull=True)   # an Effort has one track file at most
    target = free.filter(effort_date=t.survey_date).first() or free.order_by("legacy_daily_effort_id").first()
    trackfix.link(u, t, target)
    # 4. A sighting with children, deleted.
    legacy_del, id_del = one('''select s."SightingID", s.id from dbo."SightingT" s where exists
        (select 1 from dbo."OtherSpeciesT" o where o.sighting_id = s.id) order by 1 limit 1''')
    r3 = c.post(f"/sightings/{legacy_del}/delete/", {"confirmed": "1"})
    children = one('select count(*) from dbo."OtherSpeciesT" where sighting_id = %s', [id_del])[0]
    codes = [r.status_code, r2.status_code, r3.status_code]
    if codes != [302, 302, 302]:
        raise SystemExit(f"a form was not accepted: {codes}")
    json.dump({"sighting": [s.pk, s.legacy_sighting_id, species], "effort": [e.pk, e.legacy_daily_effort_id],
               "track": [t.legacy_track_id, target.pk, target.legacy_daily_effort_id],
               "deleted": [id_del, legacy_del], "codes": codes,
               "children_left": children}, open(STATE, "w"))
    print("made:", open(STATE).read())
else:
    st = json.load(open(STATE))
    out = {}
    out["sighting"] = one('select "Comments", species_id, num_calves, depth_m::text from dbo."SightingT" '
                          'where id = %s', [st["sighting"][0]])
    out["effort"] = one('select "Locality", total_distance_nm::text from dbo."DailyEffortT" where id = %s',
                        [st["effort"][0]])
    out["track"] = one('select daily_effort_id, track_status, "EffortID" from dbo."TrackT" where "TrackID" = %s', [st["track"][0]])
    out["deleted sighting"] = one('select count(*) from dbo."SightingT" where id = %s', [st["deleted"][0]])
    out["its other species"] = one('select count(*) from dbo."OtherSpeciesT" where sighting_id = %s', [st["deleted"][0]])
    ok = (out["sighting"] == ("Edited before a rebuild.", st["sighting"][2], 7, "123.45")
          and out["effort"] == ("Locality Edited Before A Rebuild", "42.125")
          and out["track"][0] == st["track"][1] and out["track"][1] in ("available", "blank")
          and out["deleted sighting"][0] == 0 and out["its other species"][0] == 0)
    print("after the rebuild:", out)
    print("PASSED" if ok else "FAILED")
    if not ok:
        raise SystemExit(1)
