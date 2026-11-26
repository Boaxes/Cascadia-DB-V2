"""
Delete every track file, put every one back the way people do on the website,
and prove the result is the same as before.

This is a test for a scratch copy of the database and a scratch bucket folder,
never the live site. It refuses any database whose name does not start with
test_, and refuses test_today, test_last, test_review and reference.

The five steps, each one a command:

    capture   write down today's state: for every track file the SHA-256 of
              its bytes (from a read-only folder of the original files), its
              row in app.track_geometry (line, point count, length) and every
              track record in dbo.TrackT.
    teardown  empty app.track_geometry and check the bucket folder is empty.
              The track records stay: DB167 holds the file names.
    restore   through the website's own JSON pages, signed in as a test
              superuser: Fill From File (preview, then confirm) for every file
              a track names, Import Files for every file no track names, then
              Match To Effort for any file whose Effort is not what it was.
    compare   read the rebuilt state the same way as capture and list every
              difference from it, one line per file and column.
    (The dbt builds, and the Django command create_blank_track_files that
     makes the header-only files no upload can carry, run between these;
     rebuild_all_track_files.sh runs the whole sequence in order.)

Run it inside a container of the web image, on the compose network:

    docker run --rm --network cascadia_default \\
        -v <worktree>/ETL/verify:/verify:ro \\
        -v <reference folder>:/reference:ro \\
        -v <bucket folder of the test site>:/bucket \\
        -v <folder for reports>:/out \\
        -e C2_PASSWORD=... \\
        cascadia-web python -I /verify/rebuild_all_track_files.py capture --db test_c2 --out /out/expected.json

(`-I` is Python's isolated mode; the script lives in a folder of its own.)
"""

import argparse
import concurrent.futures
import hashlib
import json
import os
import sys
import threading
import time

import psycopg

URL = "postgresql://cascadia:cascadia@db:5432/{}"
NEVER = {"test_today", "test_last", "test_review", "reference", "cascadia", "postgres"}
HEADER = b"datetime_utc,latitude,longitude\n"
ADMIN = "/cascadia-admin/tracks"


def connect(db):
    if not db.startswith("test_") or db in NEVER:
        sys.exit(f"Refusing to touch the database {db!r}.")
    return psycopg.connect(URL.format(db))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# What the state is, read the same way before and after
# ---------------------------------------------------------------------------

TRACKS_SQL = """
    SELECT t."TrackID", to_jsonb(t) - 'geom', md5(ST_AsEWKB(t.geom)), e."DailyEffortID"
    FROM   dbo."TrackT" t LEFT JOIN dbo."DailyEffortT" e ON e.id = t.daily_effort_id
    ORDER  BY t."TrackID" """

GEOMETRY_SQL = """
    SELECT object_key, etag, ST_AsEWKT(geom), md5(ST_AsEWKB(geom)), point_count, length_nm::text, track_id
    FROM   app.track_geometry ORDER BY object_key COLLATE "C" """


def database_state(conn):
    with conn.cursor() as cur:
        cur.execute(TRACKS_SQL)
        tracks = {}
        for track_id, row, geom_md5, effort in cur.fetchall():
            tracks[str(track_id)] = {
                "TrackID": track_id, "file_name": row["file_name"], "EffortID": row["EffortID"],
                "effort_legacy_id": effort, "track_status": row["track_status"],
                "geom_md5": geom_md5, "row": row}
        cur.execute(GEOMETRY_SQL)
        geometry = {r[0]: {"etag": r[1], "ewkt": r[2], "geom_md5": r[3], "point_count": r[4],
                           "length_nm": r[5], "track_id": r[6]} for r in cur.fetchall()}
        cur.execute("""SELECT e."DailyEffortID", count(*) FROM dbo."TrackT" t
                       JOIN dbo."DailyEffortT" e ON e.id = t.daily_effort_id
                       GROUP BY 1 HAVING count(*) > 1 ORDER BY 1""")
        several = {str(r[0]): r[1] for r in cur.fetchall()}
        cur.execute("SELECT to_regclass('build.multi_track_efforts') IS NOT NULL")
        allowed = {}
        if cur.fetchone()[0]:
            cur.execute("SELECT effort, tracks FROM build.multi_track_efforts ORDER BY 1")
            allowed = {str(r[0]): r[1] for r in cur.fetchall()}
        cur.execute("SELECT action, count(*) FROM app.audit_log GROUP BY 1 ORDER BY 1")
        audit = {r[0]: r[1] for r in cur.fetchall()}
    return {"tracks": tracks, "geometry": geometry, "efforts_with_several": several,
            "allowed_several": allowed, "audit": audit}


def folder_files(folder):
    """{name: (sha256, size)} for the files directly in a folder."""
    out = {}
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            data = open(path, "rb").read()
            out[name] = {"sha256": sha256(data), "size": len(data)}
    return out


def reference_files(folder, geometry):
    """The original files' hashes. A file the folder lacks must be a header-only
    file the site made (a record whose file DB167 never had): its bytes are the header."""
    files = folder_files(folder)
    for key, g in geometry.items():
        if key not in files:
            if g["point_count"] != 0:
                sys.exit(f"{key} has {g['point_count']} points but is not in the reference folder.")
            files[key] = {"sha256": sha256(HEADER), "size": len(HEADER), "header_only_made_by_site": True}
    return files


def capture(args):
    conn = connect(args.db)
    state = database_state(conn)
    files = reference_files(args.reference, state["geometry"]) if args.reference else folder_files(args.bucket)
    state["files"] = files
    state["source"] = "reference folder" if args.reference else "bucket folder"
    json.dump(state, open(args.out, "w"), indent=1, sort_keys=True)
    print(f"{len(files):,} files, {len(state['geometry']):,} geometry rows, {len(state['tracks']):,} track records "
          f"-> {args.out}")


def teardown(args):
    conn = connect(args.db)
    leftover = [n for n in os.listdir(args.bucket)]
    if leftover:
        sys.exit(f"The bucket folder is not empty ({len(leftover)} entries); refusing.")
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM dbo.\"TrackT\"")
        before = cur.fetchone()[0]
        cur.execute("DELETE FROM app.track_geometry")
        print(f"Emptied app.track_geometry ({cur.rowcount:,} rows). dbo.TrackT keeps its {before:,} records.")
    conn.commit()


# ---------------------------------------------------------------------------
# The website, as the Track File Manager pages talk to it
# ---------------------------------------------------------------------------

class Site:
    """One signed-in session. The calls are the ones track-manager.js, track_fill.html
    and track_import.html make."""

    def __init__(self, base, user, password):
        import requests
        self.base = base.rstrip("/")
        self.s = requests.Session()
        self.s.get(self.base + "/login/")
        r = self.s.post(self.base + "/login/", data={
            "username": user, "password": password, "next": ADMIN + "/",
            "csrfmiddlewaretoken": self.s.cookies["csrftoken"]})
        if "/login/" in r.url or r.status_code != 200:
            sys.exit("The test user could not sign in.")

    def _headers(self):
        return {"X-CSRFToken": self.s.cookies["csrftoken"]}

    def get(self, path, **params):
        r = self.s.get(self.base + ADMIN + path, params=params)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"ok": False, "message": r.text[:200]}

    def post(self, path, data=None, files=None):
        r = self.s.post(self.base + ADMIN + path, data=data, files=files, headers=self._headers())
        try:
            body = r.json()
        except ValueError:
            body = {"ok": False, "message": f"That did not work ({r.status_code}): {r.text[:200]}"}
        body["status"] = r.status_code
        return body


def fill_one(site, track_id, key, data, log):
    """Fill From File: choose the file, look at the preview, confirm."""
    code, now = site.get(f"/api/{track_id}/")
    if code != 200 or now.get("name") != key:
        return {"key": key, "track": track_id, "ok": False, "message": f"could not open ({code}, {now.get('name')})"}
    if not now.get("blank"):
        return {"key": key, "track": track_id, "ok": True, "skipped": "already has points"}
    started = time.time()
    preview = site.post(f"/api/{track_id}/fill/preview/", files={"file": (key, data, "text/csv")})
    if not preview.get("ok"):
        return {"key": key, "track": track_id, "ok": False, "stage": "preview", "message": preview.get("message")}
    done = site.post(f"/api/{track_id}/fill/", files={"file": (key, data, "text/csv")})
    return {"key": key, "track": track_id, "ok": bool(done.get("ok")), "stage": "fill",
            "message": done.get("message"), "dropped": preview.get("dropped"),
            "preview_points": (preview.get("new") or {}).get("points"),
            "state_after": done.get("state"), "seconds": round(time.time() - started, 1)}


def restore(args):
    password = os.environ["C2_PASSWORD"]
    expected = json.load(open(args.expected))
    conn = connect(args.db)
    with conn.cursor() as cur:
        cur.execute('SELECT "TrackID", file_name FROM dbo."TrackT" WHERE file_name IS NOT NULL ORDER BY "TrackID"')
        named = {}
        for track_id, name in cur.fetchall():
            named.setdefault(name.lower(), []).append(track_id)
    wanted = {k: v for k, v in expected["files"].items()}
    ref_files = {k for k in os.listdir(args.reference) if os.path.isfile(os.path.join(args.reference, k))}
    fills, unnamed, header_only = [], [], []
    for key in sorted(wanted):
        if key not in ref_files or wanted[key]["sha256"] == sha256(HEADER):
            header_only.append(key)
        elif key.lower() in named:
            fills.append((key, named[key.lower()][0]))
        else:
            unnamed.append(key)
    unnamed.sort(key=lambda k: k.encode())
    print(f"{len(fills):,} files to Fill From File, {len(unnamed):,} files no track names to Import, "
          f"{len(header_only):,} header-only files the website cannot upload.")
    log = {"fills": [], "imports": [], "preview_suggestions": {}, "matches": [], "header_only": header_only,
           "unnamed": unnamed}
    started = time.time()

    local = threading.local()

    def site():
        if not hasattr(local, "site"):
            local.site = Site(args.base, args.user, password)
        return local.site

    def work(item):
        key, track_id = item
        return fill_one(site(), track_id, key, open(os.path.join(args.reference, key), "rb").read(), log)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for n, result in enumerate(pool.map(work, fills), 1):
            log["fills"].append(result)
            if not result["ok"]:
                print("  FAILED", result)
            if n % 100 == 0:
                print(f"  {n:,} of {len(fills):,} filled ({time.time() - started:,.0f}s)", flush=True)

    # Import Files, for the files no track names. A person is shown the suggested
    # Effort for each; it is accepted when today's data has that Effort on the
    # file and left blank when it does not.
    by_name = {t["file_name"].lower(): t for t in expected["tracks"].values() if t["file_name"]}
    me = site()
    batch, size = [], 0
    batches = []
    for key in unnamed:
        n = os.path.getsize(os.path.join(args.reference, key))
        if size + n > 50 * 1024 * 1024 and batch:
            batches.append(batch)
            batch, size = [], 0
        batch.append(key)
        size += n
    if batch:
        batches.append(batch)
    for group in batches:
        uploads = [("files", (k, open(os.path.join(args.reference, k), "rb").read(), "text/csv")) for k in group]
        preview = me.post("/api/import/preview/", files=uploads)
        if not preview.get("ok"):
            print("  IMPORT PREVIEW FAILED", preview.get("message"))
            continue
        choices = {}
        for info in preview["files"]:
            log["preview_suggestions"][info["name"]] = info.get("best")
            today = by_name.get(info["name"].lower())
            effort = today["effort_legacy_id"] if today else None
            if effort is not None:
                choices[info["name"]] = str(effort)
        uploads = [("files", (k, open(os.path.join(args.reference, k), "rb").read(), "text/csv")) for k in group]
        done = me.post("/api/import/", data={"choices": json.dumps(choices)}, files=uploads)
        log["imports"].extend(done.get("done", [{"ok": False, "message": done.get("message")}]))
    print(f"  imported {sum(1 for d in log['imports'] if d['ok'])} of {len(unnamed)}")

    # Match To Effort: only for a record whose Effort now is not the one it had.
    with conn.cursor() as cur:
        cur.execute("""SELECT t."TrackID", t.file_name, e."DailyEffortID" FROM dbo."TrackT" t
                       LEFT JOIN dbo."DailyEffortT" e ON e.id = t.daily_effort_id""")
        now = {name.lower(): (tid, eff) for tid, name, eff in cur.fetchall() if name}
    for t in sorted(expected["tracks"].values(), key=lambda t: t["TrackID"]):
        mine = now.get((t["file_name"] or "").lower())
        if mine is None or t["effort_legacy_id"] == mine[1]:
            continue
        if t["effort_legacy_id"] is None:
            log["matches"].append({"track": mine[0], "wanted": None, "had": mine[1], "ok": False,
                                   "message": "matched to an Effort today's data does not have; left alone"})
            continue
        answer = me.post(f"/api/{mine[0]}/match/", data={"effort": str(t["effort_legacy_id"])})
        log["matches"].append({"track": mine[0], "wanted": t["effort_legacy_id"], "had": mine[1],
                               "ok": bool(answer.get("ok")), "message": answer.get("message")})
    json.dump(log, open(args.out, "w"), indent=1)
    failed = [r for r in log["fills"] + log["imports"] if not r["ok"]]
    print(f"Fill: {sum(1 for r in log['fills'] if r['ok'] and not r.get('skipped')):,} done, "
          f"{sum(1 for r in log['fills'] if r.get('skipped'))} skipped, failed {len(failed)}; "
          f"matches needed {len(log['matches'])}; {time.time() - started:,.0f}s -> {args.out}")


# ---------------------------------------------------------------------------
# The comparison
# ---------------------------------------------------------------------------

CHECKED = ("TrackID", "file_name", "EffortID", "effort_legacy_id", "track_status")


def differences(expected, final, baseline=None):
    """Every difference, as {kind, key, field, expected, final, same_as_baseline}."""
    out = []

    def add(kind, key, field, e, f, b=None, has_baseline=False):
        out.append({"kind": kind, "key": key, "field": field, "expected": e, "final": f,
                    "same_as_baseline": (f == b) if has_baseline else None})

    base = baseline or {}
    # (a) bytes
    ef, ff, bf = expected["files"], final["files"], base.get("files", {})
    for key in sorted(ef.keys() | ff.keys()):
        e, f = ef.get(key), ff.get(key)
        if e is None:
            add("bucket: extra file", key, "sha256", None, f["sha256"])
        elif f is None:
            add("bucket: file missing", key, "sha256", e["sha256"], None)
        elif e["sha256"] != f["sha256"]:
            add("bucket: bytes differ", key, "sha256", e["sha256"], f["sha256"],
                (bf.get(key) or {}).get("sha256"), bool(baseline))
    # (b) lines
    eg, fg, bg = expected["geometry"], final["geometry"], base.get("geometry", {})
    for key in sorted(eg.keys() | fg.keys()):
        e, f = eg.get(key), fg.get(key)
        if e is None:
            add("geometry: extra row", key, "row", None, "present")
        elif f is None:
            add("geometry: row missing", key, "row", "present", None)
        else:
            for field in ("geom_md5", "point_count", "length_nm", "etag", "track_id"):
                if e[field] != f[field]:
                    add(f"geometry: {field} differs", key, field, e[field], f[field],
                        (bg.get(key) or {}).get(field), bool(baseline))
    # (c) track records, by TrackID; a record the import numbered again, by file name
    et, ft, bt = expected["tracks"], final["tracks"], base.get("tracks", {})
    final_by_name = {}
    for t in ft.values():
        final_by_name.setdefault((t["file_name"] or "").lower(), []).append(t)
    matched_final = set()
    for tid in sorted(et, key=int):
        e = et[tid]
        f = ft.get(tid)
        if f is not None and (f["file_name"] or "").lower() != (e["file_name"] or "").lower():
            add("track: TrackID now names another file", tid, "file_name", e["file_name"], f["file_name"])
            matched_final.add(tid)
            continue
        if f is None:
            same = [t for t in final_by_name.get((e["file_name"] or "").lower(), []) if str(t["TrackID"]) not in et]
            if len(same) != 1:
                add("track: record missing", tid, "TrackID", e["file_name"], None)
                continue
            f = same[0]
            add("track: new TrackID", tid, "TrackID", e["TrackID"], f["TrackID"])
        matched_final.add(str(f["TrackID"]))
        b = bt.get(str(f["TrackID"])) or bt.get(tid) or {}
        for field in CHECKED[1:]:
            if e[field] != f[field]:
                add(f"track: {field} differs", tid, field, e[field], f[field], b.get(field), bool(baseline))
        for column in sorted(e["row"].keys() | f["row"].keys()):
            if column in ("TrackID",) or column in CHECKED:
                continue
            if e["row"].get(column) != f["row"].get(column):
                add(f"track row: {column} differs", tid, column, e["row"].get(column), f["row"].get(column),
                    (b.get("row") or {}).get(column), bool(baseline))
        if e["geom_md5"] != f["geom_md5"]:
            add("track row: geom differs", tid, "geom", e["geom_md5"], f["geom_md5"], b.get("geom_md5"), bool(baseline))
    for tid in sorted(ft, key=int):
        if tid not in matched_final and tid not in et:
            add("track: extra record", tid, "TrackID", None, ft[tid]["file_name"])
    # (d) Efforts with several tracks
    allowed = final["allowed_several"] or expected["allowed_several"]
    for effort, count in sorted(final["efforts_with_several"].items(), key=lambda x: int(x[0])):
        if count > allowed.get(effort, 1):
            add("effort: more tracks than allowed", effort, "tracks", allowed.get(effort, 1), count)
    if expected["efforts_with_several"] != final["efforts_with_several"]:
        add("effort: the Efforts with several tracks changed", "-", "efforts",
            expected["efforts_with_several"], final["efforts_with_several"])
    return out


def compare(args):
    expected = json.load(open(args.expected))
    final_db = database_state(connect(args.db))
    final_db["files"] = (reference_files(args.reference, final_db["geometry"]) if args.reference
                         else folder_files(args.bucket))
    baseline = json.load(open(args.baseline)) if args.baseline else None
    out = differences(expected, final_db, baseline)
    json.dump({"differences": out}, open(args.out, "w"), indent=1)
    kinds = {}
    for d in out:
        kinds.setdefault(d["kind"], []).append(d)
    files_expected = len(expected["files"])
    print(f"{files_expected:,} files in the expected state; {len(final_db['files']):,} in the bucket now; "
          f"{len(expected['tracks']):,} track records expected, {len(final_db['tracks']):,} now.")
    print(f"{len(out):,} differences in {len(kinds)} kinds.")
    for kind, rows in sorted(kinds.items()):
        explained = sum(1 for r in rows if r["same_as_baseline"])
        extra = f" ({explained} the same after a plain rebuild of today's data)" if baseline else ""
        print(f"  {kind}: {len(rows):,}{extra}")
        for r in rows[:args.examples]:
            print(f"      {r['key']}: expected {str(r['expected'])[:60]!r}, now {str(r['final'])[:60]!r}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("capture", "teardown", "restore", "compare"):
        p = sub.add_parser(name)
        p.add_argument("--db", required=True)
        p.add_argument("--out")
        if name == "capture":
            p.add_argument("--reference", help="read-only folder of the original files")
            p.add_argument("--bucket", default="/bucket")
        if name in ("teardown", "compare"):
            p.add_argument("--bucket", default="/bucket")
        if name == "restore":
            p.add_argument("--base", default="http://web-c2:8000")
            p.add_argument("--user", default="c2-test")
            p.add_argument("--reference", default="/reference")
            p.add_argument("--expected", required=True)
            p.add_argument("--workers", type=int, default=3)
        if name == "compare":
            p.add_argument("--expected", required=True)
            p.add_argument("--baseline")
            p.add_argument("--reference", help="use the original files as the 'now' bytes (for the control)")
            p.add_argument("--examples", type=int, default=4)
    args = parser.parse_args()
    return {"capture": capture, "teardown": teardown, "restore": restore, "compare": compare}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
