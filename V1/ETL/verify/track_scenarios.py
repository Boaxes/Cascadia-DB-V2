#!/usr/bin/env python3
"""
Track file scenarios, as one repeatable program.

It drives the website's own HTTP endpoints (the Track File Manager, an
Effort's page and the Audit Log) the way a person's browser does, checks what
that did to the database and to the bucket folder, then rebuilds the database
with dbt and checks that every change survived. Each check prints PASS or FAIL
with the evidence, and each scenario ends with one line saying which.

    python3 ETL/verify/track_scenarios.py setup       once: the test database, bucket folder and web container
    python3 ETL/verify/track_scenarios.py run         the nine scenarios, in order
    python3 ETL/verify/track_scenarios.py run 1 2 3   only these (later ones need the earlier ones' leftovers)
    python3 ETL/verify/track_scenarios.py teardown    remove everything setup made

Only the Python standard library, the docker command and a running docker
compose "db" service are needed, plus ETL/dbt/dbt_packages (run `dbt deps` in
ETL/dbt once) for scenarios 8 and 9, which run dbt in the cascadia-etl image. The scenarios change the test database, so
run `setup` again (or `teardown` then `setup`) to start clean; they will not
run against any database that is not named in C3_DB, and never against the
protected names below.

Settings, all optional environment variables:
    C3_DB        the test database                  test_c3
    C3_WEB       the web container's name           web-c3
    C3_PORT      the port it is published on        8042
    C3_PG        the Postgres container             cascadia-db-1
    C3_BUCKET    the bucket folder on this machine  required: the web container's /bucket
    C3_SOURCE_DB the database setup copies          test_review
    C3_SOURCE_BUCKET the folder setup copies into C3_BUCKET   (none: C3_BUCKET must then already hold the files)
    C3_NETWORK   the docker network                 cascadia_default
"""

import datetime
import hashlib
import http.client
import json
import os
import pathlib
import random
import re
import shutil
import string
import subprocess
import sys
import time
import traceback
import urllib.parse
import uuid

HERE = pathlib.Path(__file__).resolve().parent
ETL = HERE.parent
DJANGO = ETL.parent / "Django"
TESTS = ETL.parent / "TESTS"

DB = os.environ.get("C3_DB", "test_c3")
WEB = os.environ.get("C3_WEB", "web-c3")
PORT = int(os.environ.get("C3_PORT", "8042"))
PG = os.environ.get("C3_PG", "cascadia-db-1")
NETWORK = os.environ.get("C3_NETWORK", "cascadia_default")
SOURCE_DB = os.environ.get("C3_SOURCE_DB", "test_review")
SOURCE_BUCKET = os.environ.get("C3_SOURCE_BUCKET", "")
BUCKET = pathlib.Path(os.environ.get("C3_BUCKET", "")) if os.environ.get("C3_BUCKET") else None
PROTECTED = {"reference", "test_today", "test_last", "test_review", "cascadia", "postgres", "template0",
             "template1", "template_postgis", "pipeline", "scratch"}

HEADER = "datetime_utc,latitude,longitude\n"
ALL_URL = "/cascadia-admin"
API = f"{ALL_URL}/tracks/api"


# ---------------------------------------------------------------------------
# Running things
# ---------------------------------------------------------------------------


def sh(args, input=None, check=True, timeout=1800):
    done = subprocess.run(args, input=input, capture_output=True, text=True, timeout=timeout)
    if check and done.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:6])} ... failed ({done.returncode}): {done.stderr.strip()[-600:]}")
    return done


def psql(sql, db=None, check=True):
    """Run SQL in the test database; returns the text printed."""
    done = sh(["docker", "exec", "-i", PG, "psql", "-U", "cascadia", "-d", db or DB, "-At", "-v", "ON_ERROR_STOP=1",
               "-f", "-"], input=sql, check=check)
    return done.stdout


def lit(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def rows(sql):
    """A query's rows as a list of dicts."""
    out = psql(f"select coalesce(json_agg(t), '[]'::json) from ({sql.rstrip().rstrip(';')}) t;")
    return json.loads(out.strip() or "[]")


def one(sql):
    found = rows(sql)
    if not found:
        return None
    return next(iter(found[0].values()))


def web_python(code):
    return sh(["docker", "exec", WEB, "python", "manage.py", "shell", "-c", code]).stdout


# ---------------------------------------------------------------------------
# The website over HTTP
# ---------------------------------------------------------------------------


class Reply:
    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, headers, body

    @property
    def text(self):
        return self.body.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.body.decode("utf-8"))

    @property
    def location(self):
        return self.headers.get("Location", "")


class Web:
    """A browser with one sign-in. Cookies are kept; redirects are not followed
    unless asked, so a 302 can be checked."""

    def __init__(self, session=None, csrf=True):
        self.cookies = {}
        self.token = "".join(random.choice(string.ascii_letters + string.digits) for _ in range(32))
        if session:
            self.cookies["sessionid"] = session
        if csrf:
            self.cookies["csrftoken"] = self.token

    def request(self, method, path, data=None, files=None, token=True, follow=False):
        headers = {"Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items())}
        body = None
        if token and "csrftoken" in self.cookies:
            headers["X-CSRFToken"] = self.token
        if files:
            boundary = "----c3" + uuid.uuid4().hex
            parts = []
            for key, value in (data or {}).items():
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
            for key, filename, content in files:
                parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'
                              "Content-Type: text/csv\r\n\r\n").encode() + content + b"\r\n")
            parts.append(f"--{boundary}--\r\n".encode())
            body = b"".join(parts)
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif data is not None:
            body = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        conn = http.client.HTTPConnection("localhost", PORT, timeout=300)
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        content = response.read()
        for name, value in response.getheaders():
            if name.lower() == "set-cookie":
                pair = value.split(";", 1)[0]
                key, _, val = pair.partition("=")
                if key in ("sessionid", "messages"):
                    if not val or "Max-Age=0" in value or "1970" in value:
                        self.cookies.pop(key, None)
                    else:
                        self.cookies[key] = val
        reply = Reply(response.status, dict(response.getheaders()), content)
        conn.close()
        if follow and reply.status in (301, 302, 303):
            return self.request("GET", reply.location, token=token)
        return reply

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, data=None, files=None, **kw):
        return self.request("POST", path, data=data if data is not None else {}, files=files, **kw)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


class Report:
    def __init__(self):
        self.scenarios = {}      # number -> {"title", "checks": [(ok, label, evidence)], "notes": []}
        self.current = None

    def start(self, number, title):
        self.current = self.scenarios[number] = {"title": title, "checks": [], "notes": []}
        print(f"\n=== Scenario {number}: {title}", flush=True)

    def check(self, ok, label, evidence=""):
        ok = bool(ok)
        self.current["checks"].append((ok, label, evidence))
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  --  {evidence}" if evidence != "" else ""), flush=True)
        return ok

    def note(self, text):
        self.current["notes"].append(text)
        print(f"  NOTE  {text}", flush=True)

    def finish(self, number):
        s = self.scenarios[number]
        failed = [c for c in s["checks"] if not c[0]]
        verdict = "PASS" if s["checks"] and not failed else "FAIL"
        print(f"SCENARIO {number} {verdict}: {s['title']} ({len(s['checks']) - len(failed)} of {len(s['checks'])} checks passed)",
              flush=True)

    def verdict(self, number):
        s = self.scenarios.get(number)
        return bool(s and s["checks"] and all(c[0] for c in s["checks"]))


R = Report()


def eq(label, got, want):
    return R.check(got == want, label, f"got {got!r}, expected {want!r}")


# ---------------------------------------------------------------------------
# What is in the bucket folder, the database and the audit log
# ---------------------------------------------------------------------------


def bfile(key):
    path = BUCKET / key
    return path.read_bytes() if path.is_file() else None


def sha(data):
    return None if data is None else hashlib.sha256(data).hexdigest()[:16]


def kept(folder, key):
    """The names under _versions/<key>/ or _deleted/<key>/, oldest first."""
    path = BUCKET / folder / key
    return sorted(p.name for p in path.iterdir() if p.is_file()) if path.is_dir() else []


def listing():
    """Every top-level csv in the bucket folder, with a short hash of it."""
    return {p.name: sha(p.read_bytes()) for p in sorted(BUCKET.iterdir()) if p.is_file() and p.name.lower().endswith(".csv")}


def track_row(track_id):
    found = rows(f'''select (to_jsonb(t) - 'geom') || jsonb_build_object('geom_md5', md5(coalesce(ST_AsEWKT(t.geom), '')),
                            'effort', (select e.legacy_daily_effort_id from app.daily_effort e where e.id = t.daily_effort_id)) as r
                     from dbo."TrackT" t where "TrackID" = {int(track_id)}''')
    return found[0]["r"] if found else None


def geometry_row(key):
    found = rows(f'''select object_key, etag, md5(coalesce(ST_AsEWKT(geom), '')) as geom_md5, point_count,
                            length_nm::text as length_nm, built_at::text as built_at, track_id
                     from app.track_geometry where object_key = {lit(key)}''')
    return found[0] if found else None


def snap(track_id, key=None):
    """Everything about one track: its record, its geometry row, its file and
    the folders of earlier versions and deleted copies."""
    row = track_row(track_id)
    key = key or (row or {}).get("file_name")
    return {"row": row, "geometry": geometry_row(key) if key else None, "file": sha(bfile(key)) if key else None,
            "versions": kept("_versions", key) if key else [], "deleted": kept("_deleted", key) if key else []}


def differences(a, b, skip=()):
    out = []
    for k in sorted(set(a) | set(b)):
        if k in skip:
            continue
        if a.get(k) != b.get(k):
            out.append(f"{k}: {a.get(k)!r} -> {b.get(k)!r}")
    return out


def same_state(label, before, after):
    """The record, geometry and file are as they were. Versions and deleted
    copies are reported but not compared, since an undo keeps what it replaces."""
    problems = []
    if (before["row"] is None) != (after["row"] is None):
        problems.append(f"record: {'present' if before['row'] else 'absent'} -> {'present' if after['row'] else 'absent'}")
    elif before["row"]:
        problems += ["record " + d for d in differences(before["row"], after["row"])]
    if before["geometry"] != after["geometry"]:
        problems.append(f"geometry: {before['geometry']} -> {after['geometry']}")
    if before["file"] != after["file"]:
        problems.append(f"file bytes: {before['file']} -> {after['file']}")
    return R.check(not problems, label, "identical (record, geometry, file bytes)" if not problems else "; ".join(problems))


def audit_max():
    return one("select coalesce(max(id), 0) from app.audit_log")


def audit_since(mark, track_id=None):
    where = f"id > {int(mark)}" + (f" and target_table = 'TrackT' and target_pk = '{int(track_id)}'" if track_id is not None else "")
    return rows(f"select id, action, target_table, target_pk, actor_name, comment, changes, restored_by "
                f"from app.audit_log where {where} order by id")


def audit_total():
    return one("select count(*) from app.audit_log")


def counts():
    return {"tracks": one('select count(*) from dbo."TrackT"'), "geometry": one("select count(*) from app.track_geometry"),
            "audit": audit_total(), "files": len(listing())}


def effort(legacy):
    found = rows(f'''select e.id, e.legacy_daily_effort_id as legacy, e.effort_date::text as date, e.research_group as grp,
                            v.code as vessel from app.daily_effort e left join app.vessel v on v.id = e.vessel_id
                     where e.legacy_daily_effort_id = {int(legacy)}''')
    return found[0] if found else None


def tracks_on(legacy):
    return rows(f'''select t."TrackID" as id, t.file_name from dbo."TrackT" t
                    join app.daily_effort e on e.id = t.daily_effort_id
                    where e.legacy_daily_effort_id = {int(legacy)} order by 1''')


def allowed_efforts():
    """The 31 Efforts that already had more than one track: {DB167 id: how many}."""
    return {r["effort"]: r["tracks"] for r in rows("select effort, tracks from build.multi_track_efforts")}


def free_efforts(count=1, group="CRC", avoid_dates=(), unique_dates=True, vessels=False):
    """Efforts with no track, newest first, each on its own date by default."""
    avoid = ",".join(lit(d) for d in avoid_dates)
    found = rows(f'''select e.legacy_daily_effort_id as legacy, e.effort_date::text as date, v.code as vessel
                     from app.daily_effort e left join app.vessel v on v.id = e.vessel_id
                     where e.research_group = {lit(group)} and e.effort_date is not null and v.code is not null
                       and not exists (select 1 from dbo."TrackT" t where t.daily_effort_id = e.id)
                       and e.effort_date::text <> all ({('array[' + avoid + ']') if avoid else 'array[]'}::text[])
                       and e.effort_date between '2016-01-01' and '2026-12-31'
                     order by e.effort_date desc, e.legacy_daily_effort_id''')
    out, seen = [], set()
    for r in found:
        if unique_dates and r["date"] in seen:
            continue
        seen.add(r["date"])
        out.append(r)
        if len(out) == count:
            break
    return out


def own_file_tracks(where, count, used=(), order="t.\"TrackID\""):
    """Tracks whose file no other record names, and whose Effort (if any) has
    just that one track and is not one of the 31."""
    found = rows(f'''select t."TrackID" as id, t.file_name, e.legacy_daily_effort_id as effort
                     from dbo."TrackT" t left join app.daily_effort e on e.id = t.daily_effort_id
                     where t.file_name is not null and {where}
                       and (select count(*) from dbo."TrackT" o where lower(o.file_name) = lower(t.file_name)) = 1
                       and (t.daily_effort_id is null or (select count(*) from dbo."TrackT" o
                                                          where o.daily_effort_id = t.daily_effort_id) = 1)
                       and coalesce(e.legacy_daily_effort_id, 0) not in (select effort from build.multi_track_efforts)
                     order by {order}''')
    out = [r for r in found if r["id"] not in used and bfile(r["file_name"]) is not None]
    return out[:count]


# ---------------------------------------------------------------------------
# GPS text made for the tests
# ---------------------------------------------------------------------------


def zigzag(first_utc, count=40, lat=33.50, lon=-117.70, amp=0.002, step=0.001):
    """Points a minute apart that zig and zag, so cleaning and line simplifying
    keep every one of them: [(time text, lat, lon)]."""
    start = datetime.datetime.fromisoformat(first_utc)
    return [((start + datetime.timedelta(seconds=60 * i)).strftime("%Y-%m-%d %H:%M:%S"),
             round(lat + (i % 2) * amp, 6), round(lon + i * step, 6)) for i in range(count)]


def cleaned_text(points):
    return HEADER + "".join(f"{t},{la:.6f},{lo:.6f}\n" for t, la, lo in points)


def expected_ewkt(points):
    return "SRID=4326;MULTILINESTRING((" + ",".join(f"{lo:.6f} {la:.6f}" for _, la, lo in points) + "))"


def text_points(text):
    out = []
    for line in text.split("\n")[1:]:
        if line:
            t, la, lo = line.split(",")
            out.append((t, float(la), float(lo)))
    return out


def geometry_matches(key, points):
    """The stored line is exactly the line these points make, and its length is
    what PostGIS says that line is."""
    ewkt = expected_ewkt(points)
    got = rows(f'''select ST_OrderingEquals(g.geom, ST_GeomFromEWKT({lit(ewkt)})) as same, g.point_count,
                          g.length_nm::text as length_nm,
                          round((ST_Length(ST_GeomFromEWKT({lit(ewkt)})::geography) / 1852)::numeric, 3)::text as want_nm
                   from app.track_geometry g where g.object_key = {lit(key)}''')
    if not got:
        return False, "no geometry row"
    g = got[0]
    ok = bool(g["same"]) and g["point_count"] == len(points) and g["length_nm"] == g["want_nm"]
    return ok, f"line equal: {g['same']}, points {g['point_count']} (want {len(points)}), length {g['length_nm']} nm (want {g['want_nm']})"


def pacific_noon(day):
    """A UTC time that is early afternoon on this date in Pacific time, winter or summer."""
    return f"{day} 21:00:00"


# ---------------------------------------------------------------------------
# The people who use the website, and the website's calls
# ---------------------------------------------------------------------------

SUPER = EDITOR = VIEWER = ANON = None


def sign_in():
    """Three users made for the test, signed in without a password: the
    session keys come straight from Django."""
    code = '''
import json
from django.contrib.auth.models import User, Group
from django.test import Client
from datahealth import access
access.ensure()
out = {}
for name, role, sup in (("c3-super", None, True), ("c3-editor", "Editor", False), ("c3-viewer", "Viewer", False)):
    u, _ = User.objects.get_or_create(username=name, defaults={"first_name": "C3", "last_name": name.split("-")[1].title()})
    u.is_superuser = sup; u.is_staff = sup; u.set_unusable_password(); u.save()
    u.groups.clear()
    if role:
        u.groups.add(Group.objects.get(name=role))
    c = Client(); c.force_login(u)
    out[name] = c.cookies["sessionid"].value
print("SESSIONS=" + json.dumps(out))
'''
    found = [l for l in web_python(code).splitlines() if l.startswith("SESSIONS=")][-1]
    sessions = json.loads(found[len("SESSIONS="):])
    global SUPER, EDITOR, VIEWER, ANON
    SUPER, EDITOR, VIEWER = (Web(sessions[n]) for n in ("c3-super", "c3-editor", "c3-viewer"))
    ANON = Web()


def api(path, **kw):
    return SUPER.get(f"{API}/{path}", **kw)


def call(track_id, action, data=None, who=None):
    return (who or SUPER).post(f"{API}/{track_id}/{action}/", data=data or {})


def jf(reply):
    try:
        return reply.json()
    except Exception:
        return {"ok": False, "message": f"HTTP {reply.status}, not JSON: {reply.text[:120]!r}"}


def save(track_id, text):
    return jf(call(track_id, "save", {"text": text}))


def match(track_id, effort_legacy):
    return jf(call(track_id, "match", {"effort": effort_legacy}))


def unmatch(track_id):
    return jf(call(track_id, "unmatch"))


def delete(track_id):
    return jf(call(track_id, "delete"))


def restore(track_id):
    return jf(call(track_id, "restore"))


def fill(track_id, filename, content):
    preview = jf(SUPER.post(f"{API}/{track_id}/fill/preview/", files=[("file", filename, content)]))
    return preview


def fill_confirm(track_id, filename, content):
    return jf(SUPER.post(f"{API}/{track_id}/fill/", files=[("file", filename, content)]))


def import_files(files, choices=None, preview=False):
    """files: [(name, bytes)]; choices: {name: Effort number or ''}."""
    parts = [("files", name, body) for name, body in files]
    if preview:
        return jf(SUPER.post(f"{API}/import/preview/", files=parts))
    return jf(SUPER.post(f"{API}/import/", data={"choices": json.dumps(choices or {})}, files=parts))


def import_one(name, points, effort_legacy=None):
    """Import one cleaned file, matched to an Effort or not. Returns (reply, track id or None)."""
    reply = import_files([(name, cleaned_text(points).encode())], {name: effort_legacy or ""})
    done = (reply.get("done") or [{}])[0]
    return done, done.get("id")


def undo(entry_id):
    """Undo an entry from the Audit Log page, as a person's browser does it;
    returns the message the page then shows."""
    reply = SUPER.post(f"{ALL_URL}/audit/{entry_id}/")
    page = SUPER.get(reply.location) if reply.status in (301, 302) else reply
    found = re.findall(r'<li[^>]*class="[^"]*(?:message|success|error)[^"]*"[^>]*>(.*?)</li>', page.text, re.S)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", " ".join(found))).strip()
    return reply.status, text


def entry_exists(entry_id):
    return one(f"select count(*) from app.audit_log where id = {int(entry_id)}") == 1


def refused(label, reply, before_counts, before_audit, words=None):
    """A refused change: an error, a sentence saying why, and nothing written."""
    ok = reply.get("ok") is False
    message = reply.get("message", "")
    nothing = counts() == before_counts and audit_max() == before_audit
    good = ok and (words is None or words.lower() in message.lower()) and nothing
    R.check(good, label, f"ok={reply.get('ok')}, message={message[:150]!r}, nothing written={nothing}")
    return good


# ---------------------------------------------------------------------------
# setup and teardown
# ---------------------------------------------------------------------------


def guard():
    if DB in PROTECTED:
        raise SystemExit(f"{DB} is a protected database; this program will not touch it.")
    if BUCKET is None:
        raise SystemExit("Set C3_BUCKET to the bucket folder for this test.")


def setup():
    guard()
    print(f"Database {DB} from {SOURCE_DB}")
    exists = psql(f"select count(*) from pg_database where datname = {lit(DB)}", db="postgres").strip()
    if exists == "0":
        done = sh(["docker", "exec", PG, "psql", "-U", "cascadia", "-d", "postgres", "-c",
                   f"create database {DB} template {SOURCE_DB}"], check=False)
        if done.returncode != 0:
            # The source is in use by its own web container, so copy it with a dump instead.
            sh(["docker", "exec", PG, "psql", "-U", "cascadia", "-d", "postgres", "-c", f"create database {DB} template template_postgis"])
            sh(["docker", "exec", PG, "sh", "-c",
                f"pg_dump -U cascadia -d {SOURCE_DB} -Fc -f /tmp/{DB}.dump && pg_restore -U cascadia -d {DB} --no-owner /tmp/{DB}.dump; rm -f /tmp/{DB}.dump"])
    if SOURCE_BUCKET and not any(BUCKET.iterdir() if BUCKET.exists() else []):
        BUCKET.mkdir(parents=True, exist_ok=True)
        subprocess.run(["cp", "-R", SOURCE_BUCKET.rstrip("/") + "/.", str(BUCKET)], check=True)
    present = sh(["docker", "ps", "-a", "--filter", f"name=^{WEB}$", "--format", "{{.Names}}"]).stdout.strip()
    if not present:
        sh(["docker", "run", "-d", "--name", WEB, "--network", NETWORK, "-p", f"{PORT}:8000",
            "-v", f"{DJANGO}:/app", "-v", f"{TESTS}:/TESTS", "-v", f"{BUCKET}:/bucket",
            "-e", f"DATABASE_URL=postgresql://cascadia:cascadia@db:5432/{DB}", "-e", "SPACES_LOCAL_DIR=/bucket",
            "-e", "SPACES_KEY=", "-e", "SPACES_SECRET=", "-e", "SPACES_ENDPOINT=", "-e", "SPACES_URL=",
            "-e", "DJANGO_DEBUG=True", "-e", "DJANGO_SECRET_KEY=local-test", "-e", "DJANGO_ALLOWED_HOSTS=*",
            "-e", "PYTHONPATH=/", "cascadia-web", "python", "manage.py", "runserver", "0.0.0.0:8000"])
        time.sleep(8)
    print("ready")


def teardown():
    guard()
    sh(["docker", "rm", "-f", WEB], check=False)
    sh(["docker", "exec", PG, "psql", "-U", "cascadia", "-d", "postgres", "-c", f"drop database if exists {DB} with (force)"], check=False)
    if BUCKET and BUCKET.exists():
        shutil.rmtree(BUCKET)
    stash = BUCKET.parent / (BUCKET.name + "_stash") if BUCKET else None
    if stash and stash.exists():
        shutil.rmtree(stash)
    print("removed")


# ---------------------------------------------------------------------------
# dbt
# ---------------------------------------------------------------------------


def dbt(*args):
    return sh(["docker", "run", "--rm", "--network", NETWORK, "-v", f"{ETL}:/app", "-w", "/app/dbt",
               "-e", "PGHOST=db", "-e", f"PGDATABASE={DB}", "cascadia-etl", "dbt", *args, "--profiles-dir", "."],
              check=False)


def rebuild(label):
    """dbt build, then swap. Returns (build ok, swap ok, text of both)."""
    t = time.time()
    built = dbt("build", "--exclude", "package:elementary")
    log = built.stdout + built.stderr
    summary = re.findall(r"Done\. PASS=\d+.*", log)
    ok = built.returncode == 0
    failing = re.findall(r"(?:FAIL|ERROR) .*", log)[:6] if not ok else []
    print(f"  ... {label}: dbt build {'finished' if ok else 'FAILED'} in {time.time() - t:.0f}s: "
          f"{summary[-1] if summary else '(no summary)'} {' | '.join(failing)}", flush=True)
    if not ok:
        return False, False, log
    swapped = dbt("run-operation", "swap")
    slog = swapped.stdout + swapped.stderr
    sok = swapped.returncode == 0 and "exception" not in slog.lower() and "error" not in slog.lower().replace("error=0", "")
    gone = psql("select to_regnamespace('dbo_next') is null and to_regnamespace('app_next') is null").strip() == "t"
    print(f"  ... {label}: swap {'done' if sok and gone else 'FAILED'}  {slog.strip().splitlines()[-1][:160] if slog.strip() else ''}", flush=True)
    return True, sok and gone, log + slog


def fingerprints(schemas):
    rel = rows(f'''select n.nspname as s, c.relname as r from pg_class c join pg_namespace n on n.oid = c.relnamespace
                   where n.nspname = any(array[{",".join(lit(s) for s in schemas)}]) and c.relkind in ('r', 'v', 'm')
                   order by 1, 2''')
    sql = "".join(f'''select {lit(r["s"].removesuffix("_next") + "." + r["r"])}, count(*), md5(coalesce(string_agg(h, '' order by h), ''))
                      from (select md5(t::text) as h from "{r["s"]}"."{r["r"]}" t) x;\n''' for r in rel)
    out = {}
    for line in psql(sql, check=False).splitlines():
        name, count, digest = line.split("|")
        out[name] = (int(count), digest)
    return out


def track_map():
    """Every track as the website would show it, keyed by TrackID."""
    found = rows('''select t."TrackID" as id, t.file_name, t.daily_effort_id, e.legacy_daily_effort_id as effort,
                           t."EffortID", t.point_count, t.length_nm::text as length_nm, t.track_status,
                           md5(coalesce(ST_AsEWKT(t.geom), '')) as geom_md5, t."SurveyDate"::text as survey_date
                    from dbo."TrackT" t left join app.daily_effort e on e.id = t.daily_effort_id order by 1''')
    return {r["id"]: r for r in found}


def geometry_map():
    found = rows('''select object_key, etag, md5(coalesce(ST_AsEWKT(geom), '')) as geom_md5, point_count, length_nm::text as length_nm,
                           track_id from app.track_geometry order by 1''')
    return {r["object_key"]: r for r in found}


def deleted_ids():
    return {int(r["target_pk"]) for r in rows('''select target_pk from app.audit_log where target_table = 'TrackT'
                                                  and action = 'delete' and restored_by is null''')}


# ---------------------------------------------------------------------------
# Scenario 1: blank files
# ---------------------------------------------------------------------------

S = {}      # what one scenario leaves for the next


def scenario1():
    R.start(1, "The blank files command makes a header-only file and a geometry row for every track naming a missing file, and twice changes nothing")
    # DB167 holds only names, so some records name a file the bucket lacks. The
    # copy of the bucket has every file, so take some away, the way DB167 has it.
    shared = rows('''select lower(file_name) as k from dbo."TrackT" where file_name is not null and btrim(file_name) <> ''
                     group by 1 having count(*) > 1 order by 1 limit 1''')
    lose_matched = own_file_tracks("t.daily_effort_id is not null and t.point_count > 0", 3)
    lose_loose = own_file_tracks("t.daily_effort_id is null and t.point_count > 0", 2)
    lost = lose_matched + lose_loose
    lost_records = [dict(r, kind="matched" if r in lose_matched else "unmatched") for r in lost]
    pair = []
    if shared:
        pair = rows(f'''select "TrackID" as id, file_name from dbo."TrackT" where lower(file_name) = {lit(shared[0]["k"])} order by 1''')
    stash = BUCKET.parent / (BUCKET.name + "_stash")
    stash.mkdir(exist_ok=True)
    missing_names = set()
    for r in lost_records + [dict(p, kind="shared") for p in pair]:
        name = r["file_name"]
        if (BUCKET / name).is_file():
            shutil.move(str(BUCKET / name), str(stash / name))
        missing_names.add(name.lower())
    names_sql = ",".join(lit(n) for n in missing_names)
    psql(f'''delete from app.track_geometry where lower(object_key) in ({names_sql});
             update dbo."TrackT" set point_count = null, length_nm = null, geom = null,
                    track_status = case when daily_effort_id is not null then 'blank' else 'unresolved' end
             where lower(file_name) in ({names_sql});''')
    R.note(f"arranged {len(lost_records)} tracks with one file each and {len(pair)} sharing the file {shared[0]['k'] if shared else '-'} "
           f"as missing from the bucket (DB167's state: a name, no file)")
    S["lost"] = lost_records
    S["lost_pair"] = pair

    expected = sorted(r["file_name"] for r in rows(f'''select distinct on (lower(file_name)) file_name from dbo."TrackT"
                               where file_name is not null and btrim(file_name) <> '' and lower(file_name) in ({names_sql})
                               order by lower(file_name), file_name'''))
    before = {"files": listing(), "geom": geometry_map(), "counts": counts()}
    out = sh(["docker", "exec", WEB, "python", "manage.py", "create_blank_track_files", "--dry-run"]).stdout
    eq("1.1 dry run says how many it would make", re.findall(r"([\d,]+) blank files would be made", out), [f"{len(expected):,}"])
    R.check(listing() == before["files"] and geometry_map() == before["geom"],
            "1.2 the dry run wrote nothing", "bucket files and geometry rows unchanged")

    out = sh(["docker", "exec", WEB, "python", "manage.py", "create_blank_track_files"]).stdout
    eq("1.3 the real run says how many it made", re.findall(r"([\d,]+) blank files made", out), [f"{len(expected):,}"])
    after = {"files": listing(), "geom": geometry_map()}
    made = sorted(set(after["files"]) - set(before["files"]))
    eq("1.4 exactly the missing files were added to the bucket", made, expected)
    bad = [n for n in expected if bfile(n) != HEADER.encode()]
    R.check(not bad, "1.5 each new file is the header and nothing else", f"{len(expected)} files checked; wrong: {bad[:3]}")
    bad = [n for n in expected if not (after["geom"].get(n) and after["geom"][n]["point_count"] == 0
                                       and after["geom"][n]["geom_md5"] == hashlib.md5(b"").hexdigest())]
    R.check(not bad, "1.6 each has a geometry row with point_count 0 and no line", f"{len(expected)} rows checked; wrong: {bad[:3]}")
    untouched = [n for n in before["files"] if after["files"].get(n) != before["files"][n]]
    R.check(not untouched, "1.7 files already in the bucket were not touched", f"{len(before['files'])} files compared; changed: {untouched[:3]}")
    other_geom = [n for n in before["geom"] if after["geom"].get(n) != before["geom"][n]]
    R.check(not other_geom, "1.8 other geometry rows were not touched", f"changed: {other_geom[:3]}")
    uncovered = rows('''select t."TrackID" as id, t.file_name from dbo."TrackT" t where t.file_name is not null and btrim(t.file_name) <> ''
                        and not exists (select 1 from app.track_geometry g where lower(g.object_key) = lower(t.file_name))''')
    held = {n.lower() for n in listing()}
    nofile = [r for r in rows('select "TrackID" as id, file_name from dbo."TrackT" where file_name is not null') if r["file_name"].lower() not in held]
    R.check(not uncovered and not nofile, "1.9 every track now has a file and a geometry row",
            f"tracks without a geometry row: {len(uncovered)}, without a file: {len(nofile)}")
    if pair:
        names = {p["file_name"].lower() for p in pair}
        R.check(len([n for n in made if n.lower() in names]) == 1, "1.10 two records naming one file get one file",
                f"records {[p['id'] for p in pair]} -> {[n for n in made if n.lower() in names]}")

    # Twice: nothing changes.
    mid = {"files": listing(), "geom": geometry_map(), "counts": counts()}
    out = sh(["docker", "exec", WEB, "python", "manage.py", "create_blank_track_files"]).stdout
    eq("1.11 a second run makes none", re.findall(r"([\d,]+) blank files made", out), ["0"])
    R.check(listing() == mid["files"] and geometry_map() == mid["geom"] and counts() == mid["counts"],
            "1.12 a second run changes nothing", "every file hash, every geometry row (built_at too) and every count the same")

    # The Manager can open them, and a blank track says it is blank.
    bad = []
    for r in lost_records:
        o = api(f"{r['id']}/")
        j = jf(o)
        if o.status != 200 or not j.get("blank") or j.get("text") != HEADER:
            bad.append((r["id"], o.status, j.get("blank")))
    R.check(not bad, "1.13 the Track File Manager opens each as a blank file", f"{len(lost_records)} opened; wrong: {bad}")
    S["blank_matched"] = lose_matched
    S["blank_loose"] = lose_loose
    R.finish(1)


# ---------------------------------------------------------------------------
# Scenario 2: fifty edits, one Save
# ---------------------------------------------------------------------------


def scenario2():
    R.start(2, "Fifty edits in the editor and one Save make exactly one version, one audit entry, and a recomputed geometry")
    target = free_efforts(1)[0]
    S.setdefault("used_dates", []).append(target["date"])
    name = f"{target['date'].replace('-', '')}-{target['vessel']}-c3-save.csv"
    points = zigzag(pacific_noon(target["date"]), count=60)
    done, tid = import_one(name, points, target["legacy"])
    R.check(done.get("ok"), "2.0 a matched file of 60 points to edit (imported through the website)", f"{done.get('message')} TrackID {tid}")
    if not tid:
        return R.finish(2)
    S["save_track"] = tid
    opened = api(f"{tid}/").json()
    text = opened["text"]
    R.check(text == cleaned_text(points), "2.1 the editor opens the stored text", f"{len(text.splitlines()) - 1} points")
    before = snap(tid)
    mark = audit_max()

    # Fifty edits in the editor happen in the browser. The page makes no
    # request until Save, so the server sees nothing; check that by looking
    # again after the edits.
    lines = text.split("\n")
    for k in range(1, 51):
        t, la, lo = lines[k].split(",")
        lines[k] = f"{t},{float(la) + 0.0005:.6f},{lo}"
    final = "\n".join(lines)
    R.check(snap(tid) == before and audit_max() == mark, "2.2 fifty edits before Save leave the server untouched",
            "no version, no audit entry, file and geometry unchanged")

    # The editor itself is the page's JavaScript, which this program does not run,
    # so read it: typing only redraws the page, and the one place it talks to the
    # server about a file's text is the Save button.
    js = (DJANGO / "static/survey/track-manager.js").read_text()
    typing = re.search(r'ta\.addEventListener\("input".*', js).group(0)
    refresh = re.search(r"function refresh\(\) \{.*?\n  \}\n", js, re.S).group(0)
    saves = re.findall(r'call\([^)]*"/save/"', js)
    R.check(not re.search(r"call\(|fetch\(", typing) and not re.search(r"call\(|fetch\(", refresh) and len(saves) == 1,
            "2.2b the editor makes no request while you type: only Save does",
            f"typing handler and redraw make no calls; {len(saves)} call(s) to /save/ in track-manager.js")

    reply = save(tid, final)
    R.check(reply.get("ok"), "2.3 one Save is accepted", reply.get("message", ""))
    after = snap(tid)
    new_versions = [v for v in after["versions"] if v not in before["versions"]]
    eq("2.4 exactly one version was made in _versions/", len(after["versions"]) - len(before["versions"]), 1)
    version_key = f"_versions/{before['row']['file_name']}/{new_versions[0]}" if new_versions else None
    R.check(new_versions and bfile(version_key) == text.encode(), "2.5 the version is the file as it was before the edits",
            f"{version_key}")
    R.check(bfile(before["row"]["file_name"]) == final.encode(), "2.6 the file is the final edited text", f"{sha(bfile(before['row']['file_name']))}")
    entries = audit_since(mark)
    eq("2.7 exactly one audit entry", [(e["action"], e["target_pk"]) for e in entries], [("edit_file", str(tid))])
    named = (entries[0]["changes"] or {}).get("version", {}).get("new") if entries else None
    eq("2.8 the entry names that version", named, version_key)
    ok, why = geometry_matches(before["row"]["file_name"], text_points(final))
    R.check(ok, "2.9 app.track_geometry was recomputed from the saved text", why)
    g = after["geometry"]
    R.check(g["geom_md5"] != before["geometry"]["geom_md5"] and g["etag"] == hashlib.md5(final.encode()).hexdigest(),
            "2.10 the geometry row changed and carries the new file's ETag", f"etag {g['etag']}")
    row = after["row"]
    R.check(row["point_count"] == 60 and float(row["length_nm"]) == float(g["length_nm"]) and row["track_status"] == "available",
            "2.11 the track record has the new length and count", f"points {row['point_count']}, length {row['length_nm']}, status {row['track_status']}")
    # Saving the same text again, or text with a bad line, writes nothing.
    c0, a0 = counts(), audit_max()
    refused("2.12 saving the same text again is refused", save(tid, final), c0, a0, "nothing has changed")
    bad = final.replace(lines[5], "not,a,row")
    refused("2.13 a bad line is refused with the line named", save(tid, bad), c0, a0, "need fixing")
    eq("2.14 still exactly one version", len(snap(tid)["versions"]) - len(before["versions"]), 1)
    R.finish(2)


# ---------------------------------------------------------------------------
# Scenario 3: Fill From File
# ---------------------------------------------------------------------------


def scenario3():
    R.start(3, "Fill From File on a blank file: preview, then confirm; geometry, point count and length match the CSV")
    if not S.get("blank_matched"):
        R.check(False, "3.0 a blank matched track from scenario 1 exists", "scenario 1 did not leave one")
        return R.finish(3)
    t = S["blank_matched"][0]
    tid, key = t["id"], t["file_name"]
    good = zigzag("2024-05-01 20:30:00", count=40, lat=33.55, lon=-117.65)
    # A device's own file: a byte order mark, other column names, Windows line
    # endings, and two rows that cannot be used.
    raw = "﻿DateTime,Lat,Lon\r\n" + "".join(f"{x},{la:.6f},{lo:.6f}\r\n" for x, la, lo in good[:20])
    raw += "2024-05-01 20:50:00,not_a_number,-117.6\r\n" + "".join(f"{x},{la:.6f},{lo:.6f}\r\n" for x, la, lo in good[20:])
    raw += "2024-05-01 21:20:00,33.5,117.6\r\n"
    content = raw.encode("utf-8")
    before = snap(tid)
    eq("3.0 the track starts blank", (before["row"]["point_count"], before["file"]), (None, sha(HEADER.encode())))
    mark = audit_max()
    p = fill(tid, "device.csv", content)
    R.check(p.get("ok"), "3.1 the preview works", p.get("message", ""))
    if p.get("ok"):
        eq("3.2 the preview counts 40 usable points and 2 dropped rows", (p["new"]["points"], p["dropped"]), (40, 2))
        eq("3.3 the preview shows the file as it is now: no points", p["current"]["points"], 0)
    R.check(snap(tid) == before and audit_max() == mark, "3.4 the preview wrote nothing", "file, geometry, record and audit log unchanged")
    done = fill_confirm(tid, "device.csv", content)
    R.check(done.get("ok"), "3.5 confirming fills the file", done.get("message", ""))
    after = snap(tid)
    expect_text = cleaned_text(good).encode()
    R.check(bfile(key) == expect_text, "3.6 the file holds exactly the cleaned CSV", f"{sha(bfile(key))} (want {sha(expect_text)})")
    ok, why = geometry_matches(key, good)
    R.check(ok, "3.7 geometry, point count and length match the CSV", why)
    row = after["row"]
    eq("3.8 the track record's point count and length follow", (row["point_count"], float(row["length_nm"])),
       (40, float(after["geometry"]["length_nm"])))
    R.check(row["track_status"] == "available" and row["effort"] == t["effort"], "3.9 still matched to the same Effort, now with points",
            f"status {row['track_status']}, Effort {row['effort']}")
    entries = audit_since(mark)
    eq("3.10 exactly one audit entry, a fill", [(e["action"], (e["comment"] or "").startswith("Filled")) for e in entries], [("edit_file", True)])
    eq("3.11 one version was kept (the blank file)", len(after["versions"]), 1)
    R.check(after["versions"] and bfile(f"_versions/{key}/{after['versions'][0]}") == HEADER.encode(),
            "3.12 that version is the blank header", "")
    S["filled"] = tid
    R.finish(3)


# ---------------------------------------------------------------------------
# Scenario 4: import five files
# ---------------------------------------------------------------------------


def scenario4():
    R.start(4, "Import five files and accept the suggestions: each matched to the Effort a person expects, or unmatched; nothing written before confirming")
    used = S.get("used_dates", [])
    # Dates picked from the data, each with the situation it is to show.
    one_free = rows('''with e as (select d.effort_date, d.legacy_daily_effort_id id, v.code, exists(select 1 from dbo."TrackT" t where t.daily_effort_id = d.id) taken
                                  from app.daily_effort d join app.vessel v on v.id = d.vessel_id where d.research_group = 'CRC' and d.effort_date between '2016-01-01' and '2026-12-31')
                       select effort_date::text as date, (array_agg(id) filter (where not taken))[1] as effort,
                              (array_agg(code) filter (where not taken))[1] as vessel from e
                       group by effort_date having count(*) filter (where not taken) = 1 and count(*) = 1 order by effort_date desc limit 3''')
    several = rows('''with e as (select d.effort_date, d.legacy_daily_effort_id id, v.code, exists(select 1 from dbo."TrackT" t where t.daily_effort_id = d.id) taken
                                  from app.daily_effort d join app.vessel v on v.id = d.vessel_id where d.research_group = 'CRC' and d.effort_date between '2016-01-01' and '2026-12-31')
                      select effort_date::text as date, json_agg(json_build_object('effort', id, 'vessel', code) order by code) as free
                      from e where not taken group by effort_date
                      having count(*) >= 2 and count(distinct code) = count(*) order by effort_date desc limit 3''')
    all_taken = rows('''with e as (select d.effort_date, d.legacy_daily_effort_id id, v.code, exists(select 1 from dbo."TrackT" t where t.daily_effort_id = d.id) taken
                                  from app.daily_effort d join app.vessel v on v.id = d.vessel_id where d.research_group = 'CRC' and d.effort_date between '2016-01-01' and '2026-12-31')
                        select effort_date::text as date, min(code) as vessel from e group by effort_date having bool_and(taken) order by effort_date desc limit 1''')
    no_effort_day = "2031-03-05"
    eq("4.0 the date chosen for 'no Effort' really has none", one(f"select count(*) from app.daily_effort where effort_date = '{no_effort_day}'"), 0)
    a, b, c = one_free[0], several[0], one_free[1]
    pick = b["free"][-1]
    d = lambda day, n=1: (datetime.date.fromisoformat(day) + datetime.timedelta(days=n)).isoformat()
    cases = [
        # (file name, first point UTC, the Effort a person expects)
        (f"{a['date'].replace('-', '')}-{a['vessel']}-c3-import1.csv", pacific_noon(a["date"]), a["effort"]),
        (f"{b['date'].replace('-', '')}-{pick['vessel']}-c3-import2.csv", pacific_noon(b["date"]), pick["effort"]),
        # A device that names its files by the UTC date: the file is called the next day, the first point is the evening before in Pacific time.
        (f"{d(c['date']).replace('-', '')}-{c['vessel']}-c3-import3.csv", f"{d(c['date'])} 03:00:00", c["effort"]),
        (f"{no_effort_day.replace('-', '')}-ROB-c3-import4.csv", pacific_noon(no_effort_day), None),
        (f"{all_taken[0]['date'].replace('-', '')}-{all_taken[0]['vessel']}-c3-import5.csv", pacific_noon(all_taken[0]["date"]), None),
    ]
    S["used_dates"] = used + [a["date"], b["date"], c["date"]]
    files = [(n, cleaned_text(zigzag(t, count=30, lat=33.40 + i * 0.05)).encode()) for i, (n, t, _) in enumerate(cases)]
    # A sixth, preview only: the name gives a vessel that is not the one Effort that day.
    other = "MUS" if a["vessel"] != "MUS" else "ROB"
    odd = (f"{a['date'].replace('-', '')}-{other}-c3-import6.csv", cleaned_text(zigzag(pacific_noon(a["date"]), count=30, lat=33.9)).encode())
    before = counts()
    mark = audit_max()
    p = import_files(files + [odd], preview=True)
    R.check(p.get("ok"), "4.1 the preview answers for all files", f"{len(p.get('files', []))} files")
    got = {f["name"]: f for f in p.get("files", [])}
    for i, (name, t, want) in enumerate(cases, 1):
        f = got.get(name, {})
        eq(f"4.{i + 1} suggestion for {name}", f.get("best"), want)
    R.check(counts() == before and audit_max() == mark, "4.7 the preview wrote nothing",
            f"before {before}, after {counts()}")
    mism = got.get(odd[0], {})
    R.note(f"preview only: {odd[0]} (vessel {other}) on a day whose one free Effort is {a['vessel']}'s ({a['effort']}): suggested {mism.get('best')}")
    S["mismatch_suggestion"] = (mism.get("best"), a["effort"], other, a["vessel"])

    choices = {n: (got.get(n, {}).get("best") or "") for n, _, _ in cases}
    done = import_files(files, choices)
    R.check(done.get("ok"), "4.8 confirming imports all five", "; ".join(f"{d_['name']}: {d_['message']}" for d_ in done.get("done", [])))
    results = {d_["name"]: d_.get("id") for d_ in done.get("done", [])}
    S["imports"] = {}
    for i, (name, t, want) in enumerate(cases, 1):
        tid = results.get(name)
        row = track_row(tid) if tid else None
        got_effort = row["effort"] if row else "no record"
        eq(f"4.{8 + i} {name} ends {'matched to Effort ' + str(want) if want else 'unmatched'}", got_effort, want)
        if row:
            S["imports"][name] = tid
            R.check(bfile(name) is not None and geometry_row(name) is not None and row["track_status"] == ("available" if want else "unassociated"),
                    f"4.{8 + i}b its file, geometry row and status", f"status {row['track_status']}, file {sha(bfile(name))}, points {row['point_count']}")
    entries = audit_since(mark)
    eq("4.14 five audit entries, all creations", sorted({e["action"] for e in entries}), ["create"])
    eq("4.15 and five of them", len(entries), 5)
    S["import_cases"] = cases
    R.finish(4)


# ---------------------------------------------------------------------------
# Scenario 5: match, unmatch, rematch, and one track per Effort
# ---------------------------------------------------------------------------


def scenario5():
    R.start(5, "Match, unmatch, match again; an Effort with a track refuses a second one by every route, except the 31 which cannot gain one")
    imports = S.get("imports", {})
    loose = [n for n in imports if n.endswith(("import4.csv", "import5.csv"))]
    if len(loose) < 2:
        R.check(False, "5.0 two unmatched imported tracks from scenario 4", f"found {loose}")
        return R.finish(5)
    U, W = imports[sorted(loose)[0]], imports[sorted(loose)[1]]
    Uname, Wname = sorted(loose)
    pool = free_efforts(4, avoid_dates=S.get("used_dates", []))
    FE1, FE2, FE3, FE4 = pool
    S["used_dates"] += [e["date"] for e in pool]
    R.note(f"U = track {U} ({Uname}), W = track {W} ({Wname}); free Efforts {[e['legacy'] for e in pool]}")

    def state(t):
        r = track_row(t)
        return (r["effort"], r["EffortID"], r["track_status"], r["daily_effort_id"] is not None) if r else None

    mark = audit_max()
    r = match(U, FE1["legacy"])
    R.check(r.get("ok"), "5.1 match U to a free Effort", r.get("message", ""))
    row = track_row(U)
    eq("5.2 the record follows (Effort, EffortID, status)", (row["effort"], row["EffortID"], row["track_status"]), (FE1["legacy"], FE1["legacy"], "available"))
    eq("5.3 one 'associate' entry", [e["action"] for e in audit_since(mark, U)], ["associate"])
    c0, a0 = counts(), audit_max()
    refused("5.4 matching it to the same Effort again is refused", match(U, FE1["legacy"]), c0, a0, "already matched")
    r = unmatch(U)
    R.check(r.get("ok"), "5.5 unmatch", r.get("message", ""))
    row = track_row(U)
    eq("5.6 the record is unmatched (Effort, EffortID, status)", (row["effort"], row["EffortID"], row["track_status"]), (None, None, "unassociated"))
    eq("5.7 the Effort is free again", len(tracks_on(FE1["legacy"])), 0)
    c0, a0 = counts(), audit_max()
    refused("5.8 unmatching a track that is not matched is refused", unmatch(U), c0, a0, "not matched")
    r = match(U, FE1["legacy"])
    R.check(r.get("ok"), "5.9 match again to the same Effort", r.get("message", ""))
    eq("5.10 matched to it", state(U)[0], FE1["legacy"])
    unmatch(U)
    r = match(U, FE2["legacy"])
    R.check(r.get("ok"), "5.11 unmatch, then match to a different Effort", r.get("message", ""))
    eq("5.12 matched to the new one and the old is free", (state(U)[0], len(tracks_on(FE1["legacy"])), len(tracks_on(FE2["legacy"]))), (FE2["legacy"], 0, 1))
    r = match(U, FE3["legacy"])
    R.note(f"matching a track that is already matched straight to another free Effort: ok={r.get('ok')} "
           f"({r.get('message')}); now on {state(U)[0]}, Effort {FE2['legacy']} has {len(tracks_on(FE2['legacy']))} track(s)")
    consistent = state(U)[0] == (FE3["legacy"] if r.get("ok") else FE2["legacy"])
    R.check(consistent and len(tracks_on(FE2["legacy"])) + len(tracks_on(FE3["legacy"])) == 1,
            "5.13 a direct move leaves it on exactly one Effort", f"on {state(U)[0]}")
    if state(U)[0] != FE2["legacy"]:
        FE2, FE3 = FE3, FE2          # U now sits on what was FE3; keep the names meaning "U's Effort" and "a free one"
    # U is on FE2. A different track may not take it.
    c0, a0 = counts(), audit_max()
    refused("5.14 route 'match': a second track on an Effort that has one is refused", match(W, FE2["legacy"]), c0, a0, "already has a track")
    taken_real = rows('select e.legacy_daily_effort_id as e from dbo."TrackT" t join app.daily_effort e on e.id = t.daily_effort_id order by 1 limit 1')[0]["e"]
    refused("5.15 ... also an Effort that has a real DB167 track", match(W, taken_real), c0, a0, "already has a track")
    extra = (f"{FE2['date'].replace('-', '')}-{FE2['vessel']}-c3-second.csv", cleaned_text(zigzag(pacific_noon(FE2["date"]), 20, lat=33.2)).encode())
    p = import_files([extra], {extra[0]: FE2["legacy"]})
    d_ = (p.get("done") or [{}])[0]
    R.check(d_.get("ok") is False and "already has a track" in d_.get("message", "") and counts() == c0 and bfile(extra[0]) is None,
            "5.16 route 'import with a match': refused, no file stored", f"{d_.get('message', '')[:110]!r}")
    # Add-for-effort is the same pop-up with the Effort preselected. The Effort's page does not offer it once there is a track.
    page = SUPER.get(f"/efforts/{FE2['legacy']}/").text
    free_page = SUPER.get(f"/efforts/{FE4['legacy']}/").text
    R.check("Add Track File" not in page and "Add Track File" in free_page,
            "5.17 route 'add for an Effort': the Effort's page offers Add Track File only when it has no track",
            f"Effort {FE2['legacy']} (has one): offered={'Add Track File' in page}; Effort {FE4['legacy']} (none): offered={'Add Track File' in free_page}")
    p = import_files([extra], {extra[0]: FE2["legacy"]})
    R.check((p.get("done") or [{}])[0].get("ok") is False and bfile(extra[0]) is None,
            "5.18 and posting the pop-up for that Effort anyway is refused", "")

    # Restore: delete U, give the Effort to W, then try to bring U back.
    r = delete(U)
    R.check(r.get("ok"), "5.19 delete U", r.get("message", ""))
    r = match(W, FE2["legacy"])
    R.check(r.get("ok"), "5.20 its Effort is free, so W can take it", r.get("message", ""))
    c0, a0 = counts(), audit_max()
    refused("5.21 route 'restore': bringing U back onto an Effort W now holds is refused", restore(U), c0, a0, "another track file")
    R.check(U in {int(x) for x in [r_["id"] for r_ in jf(api("files/?status=deleted")).get("files", [])]},
            "5.22 U is still in the deleted list", "")
    unmatch(W)
    r = restore(U)
    R.check(r.get("ok") and state(U)[0] == FE2["legacy"], "5.23 with W moved off, the restore works and U is back on its Effort", r.get("message", ""))

    # Undo: unmatch U, give its Effort to W, try to undo the unmatch.
    m = audit_max()
    unmatch(U)
    entry = audit_since(m, U)[-1]["id"]
    r = match(W, FE2["legacy"])
    R.check(r.get("ok"), "5.24 W takes the Effort U was unmatched from", r.get("message", ""))
    c0, a0 = counts(), audit_max()
    status, message = undo(entry)
    R.check(entry_exists(entry) and state(U)[0] is None and "another track file" in message and counts() == c0 and audit_max() == a0,
            "5.25 route 'undo': undoing U's unmatch is refused", f"HTTP {status}, page says {message[:130]!r}, entry still in the log")
    if state(W)[0] is not None:
        unmatch(W)
    status, message = undo(entry)
    R.check(not entry_exists(entry) and state(U)[0] == FE2["legacy"], "5.26 once W is off, the same undo works", f"HTTP {status}, {message[:100]!r}")

    # The 31.
    allowed = allowed_efforts()
    pair = None
    for legacy, n in allowed.items():
        both = tracks_on(legacy)
        if len(both) == n == 2 and all(bfile(t["file_name"]) is not None for t in both) \
                and all(one(f'select count(*) from dbo."TrackT" where lower(file_name) = lower({lit(t["file_name"])})') == 1 for t in both):
            pair = (legacy, both)
            break
    if not pair:
        R.check(False, "5.27 an Effort among the 31 with two tracks of its own files", "none found")
    else:
        ME, (M1, M2) = pair
        R.note(f"one of the 31: Effort {ME}, tracks {M1['id']} and {M2['id']}")
        c0, a0 = counts(), audit_max()
        refused("5.27 a third track cannot be matched to it", match(W, ME) if state(W)[0] is None else {"ok": True}, c0, a0, "already has a track")
        extra2 = (f"20200101-ROB-c3-third.csv", cleaned_text(zigzag("2020-01-01 21:00:00", 20, lat=33.1)).encode())
        e_ = effort(ME)
        extra2 = (f"{e_['date'].replace('-', '')}-{e_['vessel']}-c3-third.csv", extra2[1])
        p = import_files([extra2], {extra2[0]: ME})
        d_ = (p.get("done") or [{}])[0]
        R.check(d_.get("ok") is False and counts() == c0 and bfile(extra2[0]) is None,
                "5.28 nor imported with a match to it", f"{d_.get('message', '')[:100]!r}")
        before1, before2 = snap(M1["id"]), snap(M2["id"])
        m = audit_max()
        r = unmatch(M1["id"])
        R.check(r.get("ok"), "5.29 one of its tracks can be unmatched", r.get("message", ""))
        entry = audit_since(m, M1["id"])[-1]["id"]
        c0, a0 = counts(), audit_max()
        refused("5.30 and now that it has one, no other track can be matched to it", match(W, ME), c0, a0, "already has a track")
        status, message = undo(entry)
        R.check(not entry_exists(entry) and len(tracks_on(ME)) == 2, "5.31 undoing the unmatch puts back the track it had", f"Effort {ME} has {len(tracks_on(ME))} tracks; {message[:80]!r}")
        same_state("5.32 and that track is as it was", before1, snap(M1["id"]))
        r = delete(M1["id"])
        r2 = restore(M1["id"])
        R.check(r.get("ok") and r2.get("ok") and len(tracks_on(ME)) == 2, "5.33 a track can be deleted and restored, the Effort ending with the two it had",
                f"{r.get('message', '')[:40]} / {r2.get('message', '')[:50]}")
        same_state("5.34 the restored track is as it was", before1, snap(M1["id"]))
        same_state("5.35 its sibling was not touched", before2, snap(M2["id"]))
    S["U"], S["W"], S["U_effort"] = U, W, FE2["legacy"]
    R.finish(5)


# ---------------------------------------------------------------------------
# Scenario 6: delete, restore, and undo of each kind
# ---------------------------------------------------------------------------


def scenario6():
    R.start(6, "Delete and restore; undo import, save, fill, match, unmatch and delete from the Audit Log; each returns the exact previous state")
    used = {S.get("U"), S.get("W"), S.get("save_track"), S.get("filled")}
    matched = own_file_tracks("t.daily_effort_id is not null and t.point_count > 0 and t.track_status = 'available'", 8, used)
    loose = own_file_tracks("t.daily_effort_id is null and t.point_count > 0", 2, used)
    if len(matched) < 6 or not loose:
        R.check(False, "6.0 real tracks to work on", f"matched {len(matched)}, unmatched {len(loose)}")
        return R.finish(6)
    r_del, r_save, r_fill, r_unmatch, r_undel, r_spare = matched[:6]
    r_match = loose[0]

    # 6.1 delete, then restore
    t, key = r_del["id"], r_del["file_name"]
    before = snap(t)
    body = bfile(key)
    mark = audit_max()
    r = delete(t)
    R.check(r.get("ok"), "6.1 delete a matched track", r.get("message", ""))
    after = snap(t, key)
    R.check(after["row"] is None and after["geometry"] is None and bfile(key) is None, "6.2 its record, geometry row and file are gone from the live places", "")
    R.check(len(after["deleted"]) == 1 and bfile(f"_deleted/{key}/{after['deleted'][0]}") == body,
            "6.3 the file moved to _deleted/ byte for byte", f"_deleted/{key}/{after['deleted'][0] if after['deleted'] else '-'}")
    eq("6.4 one 'delete' entry", [e["action"] for e in audit_since(mark, t)], ["delete"])
    listed = jf(api("files/?status=deleted")).get("files", [])
    R.check(any(f["id"] == t for f in listed), "6.5 the Manager lists it among the deleted", "")
    o = jf(api(f"{t}/"))
    R.check(o.get("state") == "deleted" and o.get("text") == body.decode(), "6.6 and can open the deleted file's text", f"state {o.get('state')}")
    page = SUPER.get(f"/efforts/{r_del['effort']}/").text
    R.check(key not in page, "6.7 the Effort's page no longer lists it", "")
    r = restore(t)
    R.check(r.get("ok"), "6.8 restore", r.get("message", ""))
    same_state("6.9 row, geometry and file are back exactly as before", before, snap(t))
    R.check(snap(t)["deleted"] == [] and key in SUPER.get(f"/efforts/{r_del['effort']}/").text, "6.10 _deleted/ is empty again and the Effort lists the track", "")
    actions = [e["action"] for e in audit_since(mark, t)]
    eq("6.11 the log keeps the delete and adds a restore", actions, ["delete", "restore"])

    # 6.2 undo of each kind
    def undo_case(number, label, do, subject=None):
        """Take the state, make the change, undo it from the Audit Log."""
        tid = subject
        before = snap(tid) if tid else None
        total = audit_total()
        m = audit_max()
        new_tid = do()
        tid = tid or new_tid
        entries = audit_since(m, tid)
        if not entries:
            R.check(False, f"6.{number} {label}: the change made an audit entry", "none")
            return
        entry = entries[-1]["id"]
        status, message = undo(entry)
        R.check(not entry_exists(entry), f"6.{number} {label}: undo from the Audit Log removes the entry", f"HTTP {status} {message[:90]!r}")
        eq(f"6.{number}a the audit log is back to {total} entries", audit_total(), total)
        return before, tid

    # import
    fresh = free_efforts(1, avoid_dates=S.get("used_dates", []))[0]
    S["used_dates"].append(fresh["date"])
    name = f"{fresh['date'].replace('-', '')}-{fresh['vessel']}-c3-undo-import.csv"
    base = counts()
    got = {}

    def do_import():
        done, tid = import_one(name, zigzag(pacific_noon(fresh["date"]), 20, lat=33.3), fresh["legacy"])
        got["tid"] = tid
        return tid
    res = undo_case(12, "import", do_import)
    R.check(track_row(got["tid"]) is None and geometry_row(name) is None and bfile(name) is None and counts() == base,
            "6.12b nothing is left of the import", f"counts {counts()} (before {base})")

    # save
    t = r_save["id"]
    text = jf(api(f"{t}/"))["text"].split("\n")
    first = text[1].split(",")
    text[1] = f"{first[0]},{float(first[1]) + 0.0007:.6f},{first[2]}"
    res = undo_case(13, "save", lambda: save(t, "\n".join(text)) and t, subject=t)
    if res:
        same_state("6.13b the file, geometry and record are as they were", res[0], snap(t))

    # fill
    t = r_fill["id"]
    good = zigzag("2024-06-01 20:30:00", count=25, lat=33.7, lon=-117.9)
    content = cleaned_text(good).encode()
    res = undo_case(14, "fill", lambda: fill_confirm(t, "x.csv", content) and t, subject=t)
    if res:
        same_state("6.14b the file, geometry and record are as they were", res[0], snap(t))

    # match
    t = r_match["id"]
    free = free_efforts(1, avoid_dates=S.get("used_dates", []))[0]
    S["used_dates"].append(free["date"])
    res = undo_case(15, "match", lambda: match(t, free["legacy"]) and t, subject=t)
    if res:
        same_state("6.15b the record is as it was, unmatched", res[0], snap(t))

    # unmatch
    t = r_unmatch["id"]
    res = undo_case(16, "unmatch", lambda: unmatch(t) and t, subject=t)
    if res:
        same_state("6.16b the record is as it was, matched to the same Effort", res[0], snap(t))

    # delete (undone from the Audit Log, not restored from the Manager)
    t = r_undel["id"]
    res = undo_case(17, "delete", lambda: delete(t) and t, subject=t)
    if res:
        same_state("6.17b the record, geometry and file are back as they were", res[0], snap(t))
        R.check(snap(t)["deleted"] == [], "6.17c and the copy in _deleted/ is gone", f"{snap(t)['deleted']}")
    S["real_used"] = [r_del["id"], r_save["id"], r_fill["id"], r_unmatch["id"], r_undel["id"], r_match["id"]]
    R.finish(6)


# ---------------------------------------------------------------------------
# Scenario 7: from an Effort's page
# ---------------------------------------------------------------------------


def scenario7():
    R.start(7, "From an Effort's page: Add Track File, Edit and Delete each work, are permission-checked on the server, and are in the Audit Log")
    e = free_efforts(1, avoid_dates=S.get("used_dates", []))[0]
    S["used_dates"].append(e["date"])
    L = e["legacy"]
    page = SUPER.get(f"/efforts/{L}/")
    R.check(page.status == 200 and f"?import_effort={L}" in page.text and "Add Track File" in page.text,
            "7.1 the Effort's page offers Add Track File", f"HTTP {page.status}")
    w = SUPER.get(f"{ALL_URL}/tracks/?import_effort={L}")
    R.check(w.status == 200 and f'data-import-effort="{L}"' in w.text, "7.2 which opens the Manager at the Import pop-up for that Effort", f"HTTP {w.status}")
    pop = SUPER.get(f"{ALL_URL}/tracks/import/?effort={L}")
    R.check(pop.status == 200 and f'WANTED = "{L}"' in pop.text, "7.3 with that Effort preselected", f"HTTP {pop.status}")
    name = f"{e['date'].replace('-', '')}-{e['vessel']}-c3-effort-page.csv"
    pts = zigzag(pacific_noon(e["date"]), 30, lat=33.35)
    mark = audit_max()
    pv = import_files([(name, cleaned_text(pts).encode())], preview=True)
    eq("7.4 its preview suggests that Effort", pv["files"][0]["best"] if pv.get("files") else None, L)
    done = import_files([(name, cleaned_text(pts).encode())], {name: L})
    R.check(done.get("ok"), "7.5 Add Track File imports it matched to the Effort", (done.get("done") or [{}])[0].get("message", ""))
    tid = (done.get("done") or [{}])[0].get("id")
    S["effort_page_track"] = tid
    page = SUPER.get(f"/efforts/{L}/").text
    R.check(name in page and f"?open={tid}" in page and f"/cascadia-admin/tracks/{tid}/delete/" in page and "Add Track File" not in page,
            "7.6 the Effort's page now lists the file with Edit and Delete, and no Add", "")
    entries = audit_since(mark, tid)
    R.check([x["action"] for x in entries] == ["create"] and f"for effort {L}" in (entries[0]["comment"] or ""),
            "7.7 the Audit Log has the add", f"{[(x['id'], x['action']) for x in entries]}")

    # Edit: the Effort page's Edit link opens the Manager at the file.
    ed = SUPER.get(f"{ALL_URL}/tracks/?open={tid}")
    o = SUPER.get(f"{API}/{tid}/")
    R.check(ed.status == 200 and f'data-open="{tid}"' in ed.text and o.status == 200 and jf(o).get("effort", {}).get("id") == int(L),
            "7.8 Edit opens the Manager on that file, matched to the Effort", f"HTTP {ed.status}/{o.status}")
    text = jf(o)["text"].split("\n")
    first = text[1].split(",")
    text[1] = f"{first[0]},{float(first[1]) + 0.0003:.6f},{first[2]}"
    m = audit_max()
    s = save(tid, "\n".join(text))
    R.check(s.get("ok") and [x["action"] for x in audit_since(m, tid)] == ["edit_file"], "7.9 a change made there saves and is in the Audit Log", s.get("message", ""))

    # Permissions: nobody without access_data_health, and nobody signed out.
    epage = EDITOR.get(f"/efforts/{L}/")
    R.check(epage.status == 200 and "Add Track File" not in epage.text and f"?open={tid}" not in epage.text and f"/tracks/{tid}/delete/" not in epage.text,
            "7.10 an Editor (no Cascadia Admin) sees the Effort page with no Add/Edit/Delete", f"HTTP {epage.status}")
    vpage = VIEWER.get(f"/efforts/{L}/")
    R.check("Add Track File" not in vpage.text and f"/tracks/{tid}/delete/" not in vpage.text, "7.11 a Viewer neither", f"HTTP {vpage.status}")
    snapshot = (counts(), audit_max(), snap(tid))
    reads = [f"{ALL_URL}/tracks/", f"{ALL_URL}/tracks/import/?effort={L}", f"{ALL_URL}/tracks/?open={tid}", f"{ALL_URL}/tracks/?import_effort={L}",
             f"{ALL_URL}/tracks/{tid}/fill/", f"{API}/files/", f"{API}/{tid}/", f"{API}/{tid}/version/?key=x"]
    writes = [(f"{ALL_URL}/tracks/{tid}/delete/", {}, None), (f"{API}/import/", {"choices": "{}"}, [("files", "z.csv", cleaned_text(pts).encode())]),
              (f"{API}/import/preview/", {}, [("files", "z.csv", b"x")]), (f"{API}/{tid}/save/", {"text": "\n".join(text)}, None),
              (f"{API}/{tid}/fill/", {}, [("file", "z.csv", cleaned_text(pts).encode())]), (f"{API}/{tid}/fill/preview/", {}, [("file", "z.csv", b"x")]),
              (f"{API}/{tid}/match/", {"effort": L}, None), (f"{API}/{tid}/unmatch/", {}, None), (f"{API}/{tid}/delete/", {}, None),
              (f"{API}/{tid}/restore/", {}, None), (f"{ALL_URL}/audit/{audit_max()}/", {}, None)]
    for who, label in ((EDITOR, "an Editor"), (VIEWER, "a Viewer")):
        bad = [p for p in reads if who.get(p).status != 403]
        bad += [p for p, d, f in writes if who.post(p, data=d, files=f).status != 403]
        R.check(not bad, f"7.12 {label} is refused (403) on {len(reads) + len(writes)} Cascadia Admin addresses", f"not refused: {bad}")
    bad = [(p, ANON.get(p).status) for p in reads if ANON.get(p).status != 302 or "/login" not in ANON.get(p).location]
    bad += [(p, ANON.post(p, data=d, files=f).status) for p, d, f in writes if ANON.post(p, data=d, files=f).status != 302]
    R.check(not bad, "7.13 signed out, every one sends you to sign in (302)", f"{bad[:3]}")
    nt = Web(SUPER.cookies["sessionid"], csrf=False)
    r = nt.post(f"{API}/{tid}/delete/", token=False)
    R.check(r.status == 403, "7.14 a signed-in post with no CSRF token is refused (403)", f"HTTP {r.status}")
    R.check((counts(), audit_max(), snap(tid)) == snapshot, "7.15 none of the refused requests changed anything", "counts, audit log, file, geometry and record the same")

    # Delete from the Effort's page.
    m = audit_max()
    r = SUPER.post(f"{ALL_URL}/tracks/{tid}/delete/")
    R.check(r.status == 302 and r.location == f"/efforts/{L}/", "7.16 Delete on the Effort's page redirects back to the Effort", f"HTTP {r.status} -> {r.location}")
    after = SUPER.get(r.location)
    snap_after = snap(tid, name)
    R.check(track_row(tid) is None and bfile(name) is None and len(snap_after["deleted"]) == 1, "7.17 the track is gone and its file is in _deleted/", f"{snap_after['deleted']}")
    R.check(f"?open={tid}" not in after.text and 'Tracks <span class="muted">(0)</span>' in after.text and "Add Track File" in after.text
            and f"{name} deleted" in re.sub(r"\s+", " ", after.text),
            "7.18 the Effort's page lists no track, says the file was deleted, and offers Add Track File again", "")
    eq("7.19 the Audit Log has the delete", [x["action"] for x in audit_since(m, tid)], ["delete"])
    listing_page = SUPER.get(f"{ALL_URL}/audit/?q={tid}")
    R.check(listing_page.status == 200 and all(f"/audit/{x['id']}/" in listing_page.text for x in audit_since(mark, tid)),
            "7.20 and the Audit Log page lists the add, the change and the delete for that track", f"{len(audit_since(mark, tid))} entries")
    R.finish(7)


# ---------------------------------------------------------------------------
# Scenario 8: rebuild twice
# ---------------------------------------------------------------------------


def scenario8():
    R.start(8, "dbt build and swap twice: every change survives, builds are identical, TrackIDs never clash, one track per Effort")
    tracks0, geom0, files0, deleted0 = track_map(), geometry_map(), listing(), deleted_ids()
    allowed = allowed_efforts()
    per_effort0 = {r["e"]: r["n"] for r in rows('''select e.legacy_daily_effort_id as e, count(*) as n from dbo."TrackT" t
                                                    join app.daily_effort e on e.id = t.daily_effort_id group by 1''')}
    # The blank files command writes the file and the geometry row but not the
    # track record, which keeps its old (empty) counts until the next build.
    # So does any track whose file was blank before this test began. The build
    # is expected to fill the count in as 0, so expect that, and say how many.
    lagging = [tid for tid, t in tracks0.items() if t["point_count"] is None and (geom0.get(t["file_name"]) or {}).get("point_count") == 0]
    for tid in lagging:
        t = tracks0[tid]
        tracks0[tid] = dict(t, point_count=0, length_nm=None, track_status="blank" if t["daily_effort_id"] is not None else "unassociated")
    mine = len(set(lagging) & {x["id"] for x in S.get("lost", []) + S.get("lost_pair", [])})
    R.note(f"{len(lagging)} tracks have a blank file but no point count in dbo until a build ({mine} from the blank files command here, "
           f"{len(lagging) - mine} already so in the copied database); expected to read 0 afterwards")
    R.note(f"before: {len(tracks0)} tracks, {len(geom0)} geometry rows, {len(files0)} files, {len(deleted0)} deleted tracks")
    results = []
    for n in (1, 2):
        built, swapped, log = rebuild(f"build {n}")
        results.append((built, swapped, log))
        R.check(built, f"8.{n}a dbt build {n} passes, including its track tests", ("" if built else log[-700:]))
        if not built:
            return R.finish(8)
        tests = {name: status for status, name in re.findall(r"\d+ of \d+ (PASS|FAIL|WARN|ERROR) .*?(one_track_per_effort|track_ids_do_not_clash)", log)}
        R.check(tests.get("one_track_per_effort") == "PASS" and tests.get("track_ids_do_not_clash") == "PASS",
                f"8.{n}b the one_track_per_effort and track_ids_do_not_clash tests ran and passed", f"{tests}")
        nxt = fingerprints(["dbo_next", "app_next", "build_next"])
        S[f"next{n}"] = nxt
        R.check(swapped, f"8.{n}c swap {n} succeeds", "")
        if not swapped:
            return R.finish(8)
        S[f"live{n}"] = fingerprints(["dbo", "app"])
        tracks, geom = track_map(), geometry_map()
        S[f"tracks{n}"] = tracks
        bad = []
        for tid in sorted(set(tracks0) | set(tracks)):
            a, b = tracks0.get(tid), tracks.get(tid)
            if a != b:
                bad.append((tid, None if a is None else {k: v for k, v in a.items() if b is None or a[k] != b.get(k)}, None if b is None else {k: v for k, v in b.items() if a is None or a.get(k) != v}))
        fields = {}
        for _tid, was, now in bad:
            for k in sorted(set(was or {}) | set(now or {})):
                fields[k] = fields.get(k, 0) + 1
        R.check(not bad, f"8.{n}d after build {n}, every track is as it was (file, Effort, count, length, line, status)",
                f"{len(tracks)} tracks compared; {len(bad)} differ, in fields {fields}: {bad[:3]}")
        bad = [k for k in sorted(set(geom0) | set(geom)) if geom0.get(k) != geom.get(k)]
        R.check(not bad, f"8.{n}e geometry rows are as they were", f"{len(geom)} rows; differ: {bad[:5]}")
        R.check(listing() == files0, f"8.{n}f the bucket files are as they were", f"{len(files0)} files")
        gone = sorted(deleted0 & set(tracks))
        R.check(not gone, f"8.{n}g deleted tracks stay deleted", f"{len(deleted0)} deleted; back: {gone[:5]}")
        # Specific changes this program made through the website.
        spots = []
        for name, tid in S.get("imports", {}).items():
            spots.append((name, tid in tracks and bfile(name) is not None))
        spots.append(("save", S.get("save_track") in tracks))
        spots.append(("filled blank", tracks.get(S.get("filled"), {}).get("point_count") == 40))
        R.check(all(ok for _, ok in spots), f"8.{n}h the imports, the saved file and the filled file are all still there", f"{spots}")
    # The two builds.
    for key, what in (("next", "the build's own output (dbo, app and build, before the swap)"), ("live", "dbo and app after the swap")):
        a, b = S[f"{key}1"], S[f"{key}2"]
        differ = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        R.check(not differ, f"8.3{'a' if key == 'next' else 'b'} the checksum of every table is identical between the two builds: {what}",
                f"{len(a)} relations compared; differ: {differ[:8]}")
    # An entry is stamped (db167_checked_at) only when its state changes, so the
    # log is identical between two builds of the same inputs, stamp included.
    R.check(S["live1"].get("app.audit_log") is not None and S["live1"].get("app.audit_log") == S["live2"].get("app.audit_log"),
            "8.3c app.audit_log, db167_checked_at included, is identical between the two builds",
            f"{S['live1'].get('app.audit_log')} vs {S['live2'].get('app.audit_log')}")
    # Keys.
    dup = rows('select "TrackID" as id, count(*) from dbo."TrackT" group by 1 having count(*) > 1')
    R.check(not dup, "8.4 no TrackID is used twice", f"{dup}")
    clash = rows('''select t."TrackID" as id, t.file_name, d.target_pk from dbo."TrackT" t
                    join app.audit_log d on d.target_table = 'TrackT' and d.action = 'delete' and d.restored_by is null and d.target_pk = t."TrackID"::text''')
    R.check(not clash, "8.5 no live track has a TrackID that a deleted, unrestored track holds", f"{clash}")
    raw_clash = rows('''select c.target_pk::integer as id from app.audit_log c join raw."TrackT" r on r."TrackID" = c.target_pk::integer
                        where c.target_table = 'TrackT' and c.action = 'create' and c.restored_by is null
                          and lower(btrim(r."TrackFileName")) is distinct from lower(btrim(c.changes -> 'TrackFileName' ->> 'new'))''')
    R.check(not raw_clash, "8.6 no TrackID the website made is also a different file's DB167 TrackID", f"{raw_clash}")
    geo_clash = rows('select track_id, count(*) from app.track_geometry where track_id is not null group by 1 having count(*) > 1')
    R.check(not geo_clash, "8.7 no TrackID is saved for two bucket files", f"{geo_clash}")
    per_effort = {r["e"]: r["n"] for r in rows('''select e.legacy_daily_effort_id as e, count(*) as n from dbo."TrackT" t
                                                   join app.daily_effort e on e.id = t.daily_effort_id group by 1 having count(*) > 1''')}
    extra = {k: v for k, v in per_effort.items() if k not in allowed or v > allowed[k]}
    R.check(not extra, "8.8 no Effort outside the 31 has two tracks, and none of the 31 has more than its own number", f"{extra}")
    R.check({k: v for k, v in per_effort.items()} == {k: v for k, v in allowed.items() if per_effort0.get(k, 0) > 1},
            "8.9 each of the 31 still has the tracks it had", f"{len(per_effort)} Efforts with several tracks, {len(allowed)} allowed")
    R.finish(8)


# ---------------------------------------------------------------------------
# Scenario 9: DB167 changes under a website match
# ---------------------------------------------------------------------------


def raw_change(sql):
    """Change raw as DB167 would have: raw is a frozen snapshot that refuses
    changes, so in this test database only, the guard is lifted for the
    change and put back."""
    psql('alter table raw."DailyEffortT" disable trigger "DailyEffortT_frozen";\n' + sql +
         '\nalter table raw."DailyEffortT" enable trigger "DailyEffortT_frozen";')


def scenario9():
    R.start(9, "A website match follows its Effort when DB167 renumbers it, and the track becomes unmatched, not lost, when DB167 removes it")
    imports = S.get("imports", {})
    names = {n: t for n, t in imports.items()}
    w1_name = next((n for n in sorted(names) if n.endswith("import5.csv")), None)
    w2_name = next((n for n in sorted(names) if n.endswith("import4.csv")), None)
    if not (w1_name and w2_name) or track_row(names[w1_name]) is None or track_row(names[w2_name]) is None:
        R.check(False, "9.0 two imported tracks to match", f"{w1_name}, {w2_name}")
        return R.finish(9)
    W, W2 = names[w1_name], names[w2_name]
    for t in (W, W2):
        if track_row(t)["effort"] is not None:
            unmatch(t)
    two = free_efforts(2, avoid_dates=S.get("used_dates", []))
    target, target2 = two
    L, L2 = target["legacy"], target2["legacy"]
    before, before2 = effort(L), effort(L2)
    r = match(W, L)
    r2 = match(W2, L2)
    R.check(r.get("ok") and r2.get("ok"), "9.1 two tracks are matched to Efforts through the website",
            f"track {W} -> Effort {L}; track {W2} -> Effort {L2}")
    assoc = [e for e in audit_since(0, W) if e["action"] == "associate"][-1]["id"]
    pk = track_row(W)["daily_effort_id"]
    new_id = one('select max("DailyEffortID") + 100000 from raw."DailyEffortT"')
    raw_change(f'update raw."DailyEffortT" set "DailyEffortID" = {new_id} where "DailyEffortID" = {int(L)};')
    R.note(f"renumbered Effort {L} ({before['date']}, {before['vessel']}, {before['grp']}) to {new_id} in raw")
    built, swapped, log = rebuild("after the renumber")
    R.check(built and swapped, "9.2 the build and swap pass", "" if built else log[-500:])
    if not (built and swapped):
        return R.finish(9)
    now = effort(new_id)
    row = track_row(W)
    R.check(now is not None and effort(L) is None and (now["date"], now["vessel"], now["grp"]) == (before["date"], before["vessel"], before["grp"]),
            "9.3 the Effort now has the new number and the same date, vessel and group", f"{now}")
    R.check(row is not None and row["effort"] == new_id and row["daily_effort_id"] == pk and row["track_status"] == "available",
            "9.4 the match followed the Effort", f"track now on Effort {row['effort'] if row else None} (status {row['track_status'] if row else None}); "
            f"it should be on {new_id}, and daily_effort_id should still be {pk} (is {row['daily_effort_id'] if row else None})")
    eq("9.5 the renumbered Effort lists the track", [t["id"] for t in tracks_on(new_id)], [W])
    page = SUPER.get(f"/efforts/{new_id}/")
    R.check(page.status == 200 and w1_name in page.text and SUPER.get(f"/efforts/{L}/").status == 404,
            "9.6 on the website: the renumbered Effort's page shows the file and the old number is gone", f"HTTP {page.status}, file shown: {w1_name in page.text}")
    stale = row["EffortID"] if row else None
    R.check(stale == new_id, "9.7 (secondary) the track's own EffortID column also shows the new number",
            f"EffortID is {stale}; the Effort is now {new_id}")
    R.check(effort(stale) is None or stale == new_id, "9.8 (secondary) a stale EffortID does not now point at some other Effort", f"Effort {stale}: {effort(stale)}")
    row2 = track_row(W2)
    R.check(row2["effort"] == L2 and row2["track_status"] == "available", "9.9 the second track's match, on an Effort DB167 did not touch, is intact",
            f"on Effort {row2['effort']}")

    raw_change(f'delete from raw."DailyEffortT" where "DailyEffortID" in ({new_id}, {int(L2)});')
    R.note(f"deleted Efforts {new_id} (the renumbered one) and {L2} from raw")
    built, swapped, log = rebuild("after the delete")
    R.check(built and swapped, "9.10 the build and swap pass", "" if built else log[-500:])
    if not (built and swapped):
        return R.finish(9)
    for label, t, nm, number in (("first", W, w1_name, new_id), ("second", W2, w2_name, L2)):
        row = track_row(t)
        R.check(row is not None, f"9.11 the {label} track record is not lost", f"TrackID {t}")
        R.check(row and row["daily_effort_id"] is None and row["track_status"] not in ("available", "blank"),
                f"9.12 the {label} track is unmatched, status not matched",
                f"Effort {row['effort'] if row else None}, status {row['track_status'] if row else None}")
        R.check(bfile(nm) is not None and geometry_row(nm) is not None, f"9.13 the {label} track's file and geometry are kept", "")
        listed = jf(api(f"files/?status=unmatched&q={nm}")).get("files", [])
        R.check(any(f["id"] == t and f["state"] == "unmatched" for f in listed), f"9.14 the Track File Manager lists the {label} track as unmatched", f"{listed}")
    pipeline = SUPER.get(f"{ALL_URL}/pipeline/").text
    block = re.search(r'<details[^>]*id="entry-TrackT".*?</details>', pipeline, re.S)
    block_text = re.sub(r"<[^>]+>", " ", block.group(0)) if block else ""
    orphans = re.search(r"Orphans.*", block_text, re.S)
    summary = re.sub(r"\s+", " ", orphans.group(0))[:170] if orphans else None
    for label, t, nm in (("first", W, w1_name), ("second", W2, w2_name)):
        found = bool(orphans and re.search(r"\b%d\b" % t, orphans.group(0))) or nm in pipeline
        R.check(found, f"9.15 the Data Pipeline page's unmatched list includes the {label} track", f"TrackT entry found: {bool(block)}; its Orphans list reads {summary!r}; names track {t} or {nm}: {found}")
    r = SUPER.get(f"{ALL_URL}/audit/{assoc}/")
    R.check(r.status == 200, "9.16 the match's Audit Log entry still opens", f"HTTP {r.status}")
    R.finish(9)


# ---------------------------------------------------------------------------


SCENARIOS = {1: scenario1, 2: scenario2, 3: scenario3, 4: scenario4, 5: scenario5, 6: scenario6, 7: scenario7, 8: scenario8, 9: scenario9}


def run(which):
    guard()
    sign_in()
    for n in which:
        try:
            SCENARIOS[n]()
        except Exception:
            R.check(False, f"scenario {n} crashed", traceback.format_exc()[-900:])
    print("\n=== Summary")
    for n in which:
        if n in R.scenarios:
            s = R.scenarios[n]
            failed = [c for c in s["checks"] if not c[0]]
            print(f"  Scenario {n}: {'PASS' if s['checks'] and not failed else 'FAIL'}  {s['title'][:90]}  ({len(failed)} failed)")
    passed = sum(1 for n in which if R.verdict(n))
    print(f"{passed} of {len(which)} scenarios passed, {len(which) - passed} failed")
    return 0 if passed == len(which) else 1


def main(argv):
    if not argv or argv[0] not in ("setup", "run", "teardown"):
        print(__doc__)
        return 2
    if argv[0] == "setup":
        setup()
        return 0
    if argv[0] == "teardown":
        teardown()
        return 0
    which = [int(a) for a in argv[1:]] or sorted(SCENARIOS)
    return run(which)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
