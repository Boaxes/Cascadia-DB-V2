"""
The pipeline's site: one folder that Cloudflare Pages serves, with what each
run did.

    python site.py          # after dbt docs generate and edr report

    site/index.html         the run: its result, what it did, and the last 30 runs
    site/elementary/        Elementary's report: every model and test, with timings
                            and history across runs
    site/docs/              dbt's documentation and lineage graph
    site/reports/           the verification reports (ETL/verify)

The run's own details come from ETL/run/run.json (ETL/pipeline_run.py, made
by the workflow's steps), so a failed run is reported even when the database
could not be reached. The list of recent runs is app.pipeline_run.

.github/workflows/pipeline.yml runs this and puts the folder on Cloudflare
Pages; ops/pipeline-site.sh builds it from a local database and serves it.
"""

import datetime
import html
import json
import os
import pathlib
import shutil

HERE = pathlib.Path(__file__).parent
SITE = HERE / "site"
TARGET = HERE / "dbt" / "target"
REPORTS = HERE / "verify" / "reports"
RUN = HERE / "run"

STEP_NAMES = {
    "deps": "Install dbt's Packages",
    "tunnel-open": "Open The Tunnel To The Database",
    "check": "Check The Database Connection",
    "elementary-models": "Set Up Elementary's Tables",
    "import": "Copy DB167 Into The Database",
    "detect": "Check Whether This Is The First Run",
    "cutover": "First-Time Move Onto The New Pipeline",
    "build": "Build And Test The New Data",
    "publish": "Publish The New Data To The Website",
    "docs": "Write The Pipeline Documentation",
    "elementary-report": "Write The Elementary Report",
    "record": "Record This Run",
    "site": "Make The Report's Web Site",
    "upload": "Put The Report Online",
    "report-address": "Record The Report's Address",
}
STATUS_NAMES = {"ok": "Done", "failed": "Failed", "skipped": "Not Needed"}


def summary(path, start):
    """The lines of a report from `start` to the next blank line."""
    if not path.exists():
        return []
    lines, on = [], False
    for line in path.read_text().splitlines():
        if line.startswith(start):
            on = True
        if on:
            if not line.strip():
                break
            lines.append(line)
    return lines


def read_json(path):
    try:
        return json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return {}


def when(text):
    """An ISO time as 'Oct 20, 2026 2:00 AM Pacific' (UTC if the time zone is unknown)."""
    if not text:
        return ""
    moment = datetime.datetime.fromisoformat(str(text))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    try:
        import zoneinfo
        local = moment.astimezone(zoneinfo.ZoneInfo("America/Los_Angeles"))
        return f"{local:%b} {local.day}, {local:%Y} {local.hour % 12 or 12}:{local:%M} {local:%p} Pacific"
    except Exception:
        utc = moment.astimezone(datetime.timezone.utc)
        return f"{utc:%b} {utc.day}, {utc:%Y} {utc:%H:%M} UTC"


def length(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} second{'' if seconds == 1 else 's'}"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min {seconds} s"
    return f"{minutes // 60} h {minutes % 60} min"


def tone(result):
    return {"published": "good", "not published": "warn"}.get(result, "bad")


def recent_runs():
    """(rows, note): the last 30 rows of app.pipeline_run, or why there are none."""
    try:
        import psycopg
        import pipeline_run
        with psycopg.connect(pipeline_run.connection_url(), connect_timeout=30) as conn:
            return conn.execute("""
                select started_at, finished_at, result, git_commit, run_url, deployment_url, tests_passed, tests_failed
                from app.pipeline_run order by started_at desc limit 30
            """).fetchall(), ""
    except Exception as error:
        return [], f"The list of earlier runs could not be read from the database ({type(error).__name__})."


def esc(text):
    return html.escape(str(text))


def link(address, text):
    return f'<a href="{esc(address)}">{esc(text)}</a>' if address else esc(text)


def banner(run):
    if not run.get("result") and os.environ.get("JOB_STATUS") in ("failure", "cancelled"):
        return ('<div class="banner bad"><strong>Not Published: The Run Stopped Early</strong>The run stopped before '
                'it could record what it did, so nothing was published. The workflow run on GitHub has the details.</div>')
    if not run.get("result"):
        return ('<div class="banner warn"><strong>No Run Details</strong>This page was made without a run of '
                'the pipeline, so there is no result to show.</div>')
    result = run["result"]
    sentence = run["sentence"].split(". ", 1)[1] if ". " in run["sentence"] else run["sentence"]
    detail = f" ({esc(run['reason'])})" if run.get("reason") else ""
    off = "Turned Off Until The First Cutover" if run.get("trigger") == "schedule" else "Turned Off For This Run"
    head = {"published": "Published", "not published": f"Not Published: {off}"}.get(
        result, f"Not Published: {result.title()}")
    return f'<div class="banner {tone(result)}"><strong>{esc(head)}</strong>{esc(sentence)}{detail}</div>'


def facts(run):
    if not run.get("started_at"):
        return ""
    rows = [("Started", when(run["started_at"])), ("Finished", when(run.get("finished_at"))),
            ("Took", length((datetime.datetime.fromisoformat(run["finished_at"])
                             - datetime.datetime.fromisoformat(run["started_at"])).total_seconds())
             if run.get("finished_at") else "")]
    commit = run.get("commit", "")
    rows.append(("Git Commit", link(run.get("commit_url"), commit[:9]) if commit else "Not a GitHub run"))
    rows.append(("Started By", {"schedule": "The daily schedule", "workflow_dispatch": "A person, by hand",
                                                                 "local": "A person, on a local copy"}
                 .get(run.get("trigger"), esc(run.get("trigger", "")).title())))
    rows.append(("Publishing", "On" if run.get("publish", True) else "Off for this run"))
    rows.append(("Workflow Run", link(run.get("run_url"), "Open It On GitHub") if run.get("run_url") else "Not a GitHub run"))
    out = "".join(f"<tr><td>{esc(k)}</td><td>{v if k in ('Git Commit', 'Workflow Run', 'Started By') else esc(v)}</td></tr>"
                  for k, v in rows)
    return f'<table class="plain">{out}</table>'


def steps_table(run):
    rows = ""
    for s in run.get("steps", []):
        if s["step"] == "tunnel-close":
            continue
        rows += (f'<tr><td>{esc(STEP_NAMES.get(s["step"], s["step"]))}</td>'
                 f'<td class="{"bad" if s["status"] == "failed" else ""}">{esc(STATUS_NAMES.get(s["status"], s["status"]))}</td>'
                 f'<td>{esc(length(s["seconds"]))}</td></tr>')
    return f"<table><tr><th>Step</th><th>Result</th><th>Time</th></tr>{rows}</table>" if rows else "<p>No step details.</p>"


def build_counts(run):
    b = run.get("build") or {}
    if not b.get("found"):
        return "<p>The build did not get far enough to have results.</p>"
    rows = [("Tables And Views Built", b["models"]), ("Tables And Views That Failed", b["models_failed"]),
            ("Tests Passed", b["tests_passed"]), ("Tests Passed With A Warning", b["tests_warned"]),
            ("Tests Failed", b["tests_failed"]), ("Tests Not Run", b["tests_not_run"])]
    return ("<table class=\"plain\">" + "".join(
        f'<tr><td>{esc(k)}</td><td class="{"bad" if v and k.endswith(("Failed",)) else ""}">{v:,}</td></tr>'
        for k, v in rows) + "</table>")


def imported_table(run):
    rows = run.get("imported") or []
    if not rows:
        return "<p>No rows were copied in this run.</p>"
    body = "".join(f"<tr><td>{esc(t)}</td><td class=\"num\">{n:,}</td></tr>" for t, n in rows)
    return (f"<p>{sum(n for _, n in rows):,} rows from {len(rows)} tables.</p>"
            f"<details><summary>Rows Copied From Each Table</summary><table>{body}</table></details>")


def history(rows, note):
    if not rows:
        return f"<p>{esc(note or 'No earlier runs are recorded yet.')}</p>"
    out = ""
    for started, finished, result, commit, run_url, deployment_url, passed, failed in rows:
        out += (f'<tr><td>{esc(when(started.isoformat()))}</td>'
                f'<td><span class="tag {tone(result)}">{esc(result.title())}</span></td>'
                f'<td class="num">{"" if passed is None else f"{passed:,}"}</td>'
                f'<td class="num">{"" if failed is None else f"{failed:,}"}</td>'
                f'<td>{esc((commit or "")[:9])}</td>'
                f'<td>{link(run_url, "Run") if run_url else ""} {link(deployment_url, "Report") if deployment_url else ""}</td></tr>')
    return ("<table><tr><th>Started</th><th>Result</th><th>Tests Passed</th><th>Tests Failed</th><th>Commit</th>"
            f"<th>Links</th></tr>{out}</table>")


def main():
    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "docs").mkdir(parents=True)
    (SITE / "elementary").mkdir()
    (SITE / "reports").mkdir()
    for name in ("index.html", "manifest.json", "catalog.json"):
        if (TARGET / name).exists():
            shutil.copy(TARGET / name, SITE / "docs" / name)
    report = TARGET / "edr" / "elementary_report.html"
    has_elementary = report.exists()
    if has_elementary:
        shutil.copy(report, SITE / "elementary" / "index.html")
    has_docs = (SITE / "docs" / "index.html").exists()
    for path in REPORTS.glob("*.txt"):
        shutil.copy(path, SITE / "reports" / path.name)
    # Not for search engines.
    (SITE / "_headers").write_text("/*\n  X-Robots-Tag: noindex, nofollow\n")

    run = read_json(RUN / "run.json")
    history_rows, note = recent_runs()
    checks = (summary(REPORTS / "compare_with_live.txt", "Unexplained differences")
              + summary(REPORTS / "check_rerun.txt", "Records matched")
              + summary(REPORTS / "check_rerun.txt", "Unexplained"))
    pre = html.escape("\n".join(checks)) or "No verification reports in this run."
    verification = "".join(f'<li><a href="reports/{p.name}">{esc(p.stem.replace("_", " ").title())}</a></li>'
                           for p in sorted((SITE / "reports").glob("*.txt")))
    elementary = ('<li><a href="elementary/">Elementary Report</a>: every model and test, how long each took, '
                  'and how that changes from run to run</li>' if has_elementary else
                  '<li>The Elementary Report could not be made in this run.</li>')
    docs = ('<li><a href="docs/">Pipeline Documentation</a>: every table and view, its SQL, and the lineage graph</li>'
            if has_docs else '<li>The Pipeline Documentation could not be made in this run.</li>')
    made = datetime.datetime.now(datetime.timezone.utc).isoformat()

    (SITE / "index.html").write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Cascadia Pipeline Runs</title>
<style>
  :root {{ --bg: #ffffff; --text: #1d2327; --muted: #5d6870; --line: #d8dee3; --link: #1b5f8c;
    --good: #1e6b3a; --good-bg: #e3f3e8; --warn: #7a5200; --warn-bg: #fff2d0; --bad: #a11a1a; --bad-bg: #fde4e4; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg: #15191c; --text: #e3e8ec; --muted: #9aa5ad;
    --line: #2c343a; --link: #7cb7e0; --good: #7fd49a; --good-bg: #17301f; --warn: #f0c56a; --warn-bg: #33290f;
    --bad: #ff9c9c; --bad-bg: #3a1717; }} }}
  body {{ margin: 0; background: var(--bg); color: var(--text); font: 16px/1.5 system-ui, sans-serif; }}
  main {{ max-width: 920px; margin: 0 auto; padding: 24px 16px 48px; }}
  h1 {{ font-size: 1.6rem; margin: 0 0 12px; }} h2 {{ font-size: 1.15rem; margin: 28px 0 8px; }}
  p.muted {{ color: var(--muted); margin: 0; }} a {{ color: var(--link); }}
  table {{ border-collapse: collapse; }}
  th {{ text-align: left; font-weight: 600; border-bottom: 2px solid var(--line); padding: 4px 24px 4px 0; }}
  td {{ border-bottom: 1px solid var(--line); padding: 4px 24px 4px 0; vertical-align: top; }}
  table.plain td:first-child {{ color: var(--muted); }} td.num {{ text-align: right; }}
  td.bad {{ color: var(--bad); font-weight: 600; }}
  pre {{ white-space: pre-wrap; border: 1px solid var(--line); padding: 12px; font-size: 13px; overflow-x: auto; }}
  .banner {{ border-radius: 6px; padding: 14px 18px; margin: 0 0 16px; border: 1px solid; }}
  .banner strong {{ display: block; font-size: 1.25rem; margin-bottom: 2px; }}
  .banner.good {{ background: var(--good-bg); color: var(--good); border-color: var(--good); }}
  .banner.warn {{ background: var(--warn-bg); color: var(--warn); border-color: var(--warn); }}
  .banner.bad {{ background: var(--bad-bg); color: var(--bad); border-color: var(--bad); }}
  .tag {{ border-radius: 4px; padding: 1px 8px; font-size: 0.9rem; border: 1px solid; white-space: nowrap; }}
  .tag.good {{ background: var(--good-bg); color: var(--good); }} .tag.warn {{ background: var(--warn-bg); color: var(--warn); }}
  .tag.bad {{ background: var(--bad-bg); color: var(--bad); }}
  details {{ margin-top: 8px; }} summary {{ cursor: pointer; }}
</style></head>
<body><main>
<h1>Cascadia Pipeline Runs</h1>
{banner(run)}
{facts(run)}

<h2>What This Pipeline Is</h2>
<p>Every day around 2:00 AM Pacific, this pipeline copies the research database (DB167) into the website's database,
builds the cleaned tables the website reads from that copy, and runs tests on the result. When every test passes,
the new data is published to the website. When any test fails, nothing is published and the website keeps the data
it already had; this page then shows a red banner. A person can also start a run by hand.</p>

<h2>What This Run Did</h2>
{steps_table(run) if run.get("steps") else "<p>No step details for this page.</p>"}

<h2>Build And Tests</h2>
{build_counts(run) if run else "<p>No build details for this page.</p>"}

<h2>Rows Copied From DB167</h2>
{imported_table(run)}

<h2>Reports</h2>
<ul>
  {elementary}
  {docs}
  {verification}
</ul>

<h2>Recent Runs</h2>
{history(history_rows, note)}

{f"<h2>Verification</h2><pre>{pre}</pre>" if checks else ""}
<p class="muted">Page made {esc(when(made))}.</p>
</main></body></html>
""")
    print(f"site written to {SITE}")


if __name__ == "__main__":
    main()
