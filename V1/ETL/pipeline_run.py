"""
The small jobs around a run of the daily pipeline (.github/workflows/pipeline.yml,
ops/pipeline-steps.sh).

    python pipeline_run.py env [--shell]    the PG* variables dbt needs, from PIPELINE_DATABASE_URL
    python pipeline_run.py check            connect, and say which database this is
    python pipeline_run.py target           host:port of PIPELINE_DATABASE_URL, as the server sees it
    python pipeline_run.py detect           is this database on the new pipeline yet?
    python pipeline_run.py begin            start a run: when, which commit, which workflow run
    python pipeline_run.py record           work out the run's result, and add it to app.pipeline_run
    python pipeline_run.py url ADDRESS      add the address of the published report to the run

Everything a run learns goes in ETL/run/ (not kept in the repository): steps.tsv,
one line per step with how it ended and how long it took, build_results.json,
the last build's results from dbt, import.log, and run.json, which is what
ETL/site.py shows at the top of the report. The report is made from run.json and
not from the database, so it still tells the story of a run that could not
reach the database.

PIPELINE_TUNNEL_PORT, when set, replaces the host and port in the database
address with 127.0.0.1 and that port: the workflow reaches the server's
Postgres through an SSH tunnel.
"""

import datetime
import json
import os
import pathlib
import shlex
import sys
from urllib.parse import parse_qs, unquote, urlsplit


HERE = pathlib.Path(__file__).parent
RUN = HERE / "run"

# What a run can end as, and the sentence the report gives for it.
RESULTS = {
    "published": "Published. Every step passed and the website now shows the new data.",
    "not published": "Not Published. The new data was built and every test passed, but publishing was turned "
                     "off, so the website is still on the current data.",
    "tests failed": "Not Published. One or more tests failed, so the website is still on the current data.",
    "build failed": "Not Published. The build failed before it finished, so the website is still on the current data.",
    "import failed": "Not Published. Copying DB167 into the database failed, so nothing new was built.",
    "first-time move failed": "Not Published. The one-time move onto the new pipeline stopped before it finished. "
                              "The website is still on the current data.",
    "publish failed": "Not Published. The final step that makes the new data live failed or refused, so the "
                      "website is still on the current data.",
    "setup failed": "Not Published. The run stopped before it started on the data (setup or database connection).",
    "cancelled": "Not Published. The run was cancelled.",
}


CORE_STEPS = ("deps", "tunnel-open", "check", "elementary-models", "import", "detect", "cutover", "build", "publish")


def database_url():
    url = os.environ.get("PIPELINE_DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("PIPELINE_DATABASE_URL is not set.")
    return url


def target(url):
    parts = urlsplit(url)
    return parts.hostname or "localhost", parts.port or 5432


def connect():
    """A connection to the database (psycopg is loaded here so `begin` needs only Python)."""
    import psycopg
    return psycopg.connect(connection_url(), connect_timeout=30)


def tunnelled(url, port):
    """The address with its host and port replaced by the SSH tunnel's end."""
    parts = urlsplit(url)
    userinfo = parts.netloc.rpartition("@")[0]
    netloc = f"{userinfo}@127.0.0.1:{port}" if userinfo else f"127.0.0.1:{port}"
    return parts._replace(netloc=netloc).geturl()


def connection_url():
    url = database_url()
    port = os.environ.get("PIPELINE_TUNNEL_PORT", "").strip()
    return tunnelled(url, port) if port else url


def env_lines(url):
    parts = urlsplit(url)
    out = {
        "PIPELINE_DATABASE_URL": url,
        "PGHOST": parts.hostname or "localhost",
        "PGPORT": str(parts.port or 5432),
        "PGUSER": unquote(parts.username or ""),
        "PGPASSWORD": unquote(parts.password or ""),
        "PGDATABASE": parts.path.lstrip("/"),
    }
    sslmode = parse_qs(parts.query).get("sslmode")
    if sslmode:
        out["PGSSLMODE"] = sslmode[0]
    return out


# ---------------------------------------------------------------------------
# Is the database on the new pipeline?
# ---------------------------------------------------------------------------


def detect(conn):
    """('migrated' | 'not_migrated', why) or raises SystemExit saying what looks wrong."""

    def has_column(schema, table, column):
        return conn.execute(
            "select 1 from information_schema.columns where table_schema = %s and table_name = %s "
            "and column_name = %s", [schema, table, column]).fetchone() is not None

    def has_table(schema, table):
        return conn.execute("select to_regclass(%s)", [f'{schema}."{table}"']).fetchone()[0] is not None

    has_build = conn.execute("select to_regnamespace('build') is not null").fetchone()[0]
    sighting = has_table("dbo", "SightingT")
    hashed = sighting and has_column("dbo", "SightingT", "id")
    legacy = has_table("app", "audit_log") and has_column("app", "audit_log", "legacy_pk")
    found = (f"dbo.SightingT {'has' if hashed else 'has no'} id column, schema build "
             f"{'exists' if has_build else 'does not exist'}, app.audit_log "
             f"{'has' if legacy else 'has no'} legacy_pk column")

    if not sighting:
        raise SystemExit("This database has no dbo.SightingT, so it is neither the old structure nor the new "
                         "one. Nothing was changed. " + found + ".")
    if hashed:
        missing = [name for name, ok in (("schema build", has_build), ("app.audit_log.legacy_pk", legacy),
                                         ("app.track_geometry", has_table("app", "track_geometry")),
                                         ("app.vessel_number", has_table("app", "vessel_number"))) if not ok]
        if missing:
            raise SystemExit("dbo.SightingT has the new id column, but " + ", ".join(missing) +
                             " is missing, so this database is half moved. Nothing was changed. "
                             "It needs a person to look at it.")
        return "migrated", found

    # The old structure: what the one-time move reads from it must be there.
    need = [("dbo", "TrackT", c) for c in ("TrackID", "file_name", "geom", "point_count", "length_nm", "track_status")]
    need += [("dbo", "VesselListT", c) for c in ("vessel_id", "vessel_text")]
    need += [("app", "audit_log", "id")]
    need += [("raw", "TrackT", "TrackID"), ("raw", "VesselT", "VesselID")]
    lacking = [f"{s}.{t}.{c}" for s, t, c in need if not has_column(s, t, c)]
    if has_build or lacking:
        raise SystemExit("This database does not look like the old structure the one-time move expects. "
                         + (f"It has a schema called build. " if has_build else "")
                         + (f"Missing: {', '.join(lacking)}. " if lacking else "")
                         + "Nothing was changed.")
    return "not_migrated", found


# ---------------------------------------------------------------------------
# A run
# ---------------------------------------------------------------------------


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def read_json(path, default):
    try:
        return json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return default


def steps():
    out = []
    path = RUN / "steps.tsv"
    if path.exists():
        for line in path.read_text().splitlines():
            name, status, seconds = (line.split("\t") + ["", "", ""])[:3]
            out.append({"step": name, "status": status, "seconds": int(float(seconds or 0))})
    return out


def begin():
    RUN.mkdir(exist_ok=True)
    for old in RUN.iterdir():
        old.unlink()
    server, repo, run_id = (os.environ.get(k, "") for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    started = now()
    info = {
        "run_id": f"{run_id}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}" if run_id else f"local-{int(started.timestamp())}",
        "started_at": started.isoformat(),
        "commit": os.environ.get("GITHUB_SHA") or os.environ.get("PIPELINE_COMMIT") or "",
        "run_url": f"{server}/{repo}/actions/runs/{run_id}" if run_id else "",
        "commit_url": f"{server}/{repo}/commit/{os.environ.get('GITHUB_SHA', '')}" if run_id else "",
        "publish": os.environ.get("PUBLISH", "false") == "true",
        "trigger": os.environ.get("GITHUB_EVENT_NAME", "local"),
        "result": "",
    }
    (RUN / "run.json").write_text(json.dumps(info, indent=2))
    print(f"run {info['run_id']} started")


def counts(path):
    """Models and tests in a dbt run_results.json, by how they ended."""
    results = read_json(path, {}).get("results", [])
    out = {"models": 0, "models_failed": 0, "tests_passed": 0, "tests_warned": 0, "tests_failed": 0,
           "tests_not_run": 0, "found": bool(results)}
    for r in results:
        kind, status = r["unique_id"].split(".")[0], r["status"]
        if kind == "test":
            if status == "pass":
                out["tests_passed"] += 1
            elif status == "warn":
                out["tests_warned"] += 1
            elif status in ("fail", "error"):
                out["tests_failed"] += 1
            else:
                out["tests_not_run"] += 1
        elif kind in ("model", "seed"):
            if status in ("success", "pass"):
                out["models"] += 1
            elif status in ("error", "fail"):
                out["models_failed"] += 1
    return out


def imported():
    """(table, rows) from import.log lines like '  SightingT    123,456 rows  1.2s'."""
    out = []
    path = RUN / "import.log"
    if path.exists():
        for line in path.read_text().splitlines():
            bits = line.split()
            if len(bits) >= 3 and bits[2] == "rows" and bits[1].replace(",", "").isdigit():
                out.append((bits[0], int(bits[1].replace(",", ""))))
    return out


def work_out(done, build, job, publish, trigger):
    """(result, reason): how a run ended, from its steps, its build's counts and whether publishing was on."""
    status = {s["step"]: s["status"] for s in done}
    # The report's own extras (docs, edr) failing does not change what the run did to the data.
    failed_at = next((s["step"] for s in done if s["status"] == "failed" and s["step"] in CORE_STEPS), None)
    if job == "cancelled":
        result = "cancelled"
    elif failed_at == "import":
        result = "import failed"
    elif failed_at in ("detect", "cutover"):
        result = "first-time move failed"
    elif failed_at == "build":
        result = "build failed" if build["models_failed"] or not build["found"] or not build["tests_failed"] \
            else "tests failed"
    elif failed_at == "publish":
        result = "publish failed"
    elif failed_at or job == "failure":
        result = "setup failed"
    elif status.get("publish") == "ok":
        result = "published"
    elif status.get("build") == "ok" or status.get("cutover") == "ok":
        result = "not published"
    else:
        result = "setup failed"
    reason = ""
    if result == "not published":
        reason = ("the repository variable PIPELINE_PUBLISH is not true, which keeps scheduled runs from "
                  "publishing until the first cutover" if trigger == "schedule" and not publish
                  else "this run was started with publishing turned off" if not publish else "")
        if status.get("cutover") == "ok":
            reason += ("; " if reason else "") + ("the database is not on the new pipeline yet, so "
                                                  "only the build and its tests were tried")
    if result == "build failed" and build["models_failed"] and build["tests_failed"]:
        reason = "models failed to build and tests failed"
    return result, reason


def summarize():
    info = read_json(RUN / "run.json", {})
    done = steps()
    build = counts(RUN / "build_results.json")
    result, reason = work_out(done, build, os.environ.get("JOB_STATUS", ""), info.get("publish", True),
                              info.get("trigger", ""))
    info.update({
        "result": result,
        "sentence": RESULTS[result],
        "reason": reason,
        "finished_at": now().isoformat(),
        "steps": done,
        "build": build,
        "imported": imported(),
        "migration": (RUN / "migration").read_text().strip() if (RUN / "migration").exists() else "",
    })
    (RUN / "run.json").write_text(json.dumps(info, indent=2))
    return info


RUN_TABLE = "app.pipeline_run"


def record():
    info = summarize()
    print(f"result: {info['result']}")
    with connect() as conn:
        # The steps script makes it first (dbt run-operation create_persistent_tables).
        if conn.execute("select to_regclass(%s)", [RUN_TABLE]).fetchone()[0] is None:
            raise SystemExit(f"{RUN_TABLE} does not exist yet; run dbt run-operation create_persistent_tables first.")
        conn.execute(f"""
            insert into {RUN_TABLE} (run_id, started_at, finished_at, result, git_commit, run_url,
                                     tests_passed, tests_failed)
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (run_id) do update set started_at = excluded.started_at,
                finished_at = excluded.finished_at, result = excluded.result, git_commit = excluded.git_commit,
                run_url = excluded.run_url, tests_passed = excluded.tests_passed,
                tests_failed = excluded.tests_failed
        """, [info["run_id"], info["started_at"], info["finished_at"], info["result"], info["commit"] or None,
              info["run_url"] or None, info["build"]["tests_passed"] + info["build"]["tests_warned"],
              info["build"]["tests_failed"]])
    print(f"recorded in {RUN_TABLE}")


def add_url(address):
    info = read_json(RUN / "run.json", {})
    if not info.get("run_id"):
        raise SystemExit("There is no run to add the address to.")
    with connect() as conn:
        conn.execute(f"update {RUN_TABLE} set deployment_url = %s where run_id = %s", [address, info["run_id"]])
    print(f"the report's address is recorded: {address}")


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "env":
        for key, value in env_lines(connection_url()).items():
            print(f"export {key}={shlex.quote(value)}" if "--shell" in sys.argv else f"{key}={value}")
    elif command == "target":
        host, port = target(database_url())
        print(f"{host}:{port}")
    elif command == "check":
        with connect() as conn:
            name, version = conn.execute("select current_database(), split_part(version(), ' ', 2)").fetchone()
        print(f"connected to database {name} (PostgreSQL {version})")
    elif command == "detect":
        with connect() as conn:
            state, found = detect(conn)
        RUN.mkdir(exist_ok=True)
        (RUN / "migration").write_text(state + "\n")
        print(f"{state}: {found}")
    elif command == "begin":
        begin()
    elif command == "record":
        try:
            record()
        except (Exception, SystemExit) as error:
            print(f"The run could not be recorded in the database: {error}", file=sys.stderr)
            return 1
    elif command == "url" and len(sys.argv) > 2:
        add_url(sys.argv[2])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
