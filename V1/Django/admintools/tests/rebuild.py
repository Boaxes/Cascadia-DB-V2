"""
Running the pipeline against the test database, as a rebuild would.

The tests write through the website, then rebuild with dbt (ETL/dbt, mounted
at /dbt in the web container), and check the change is still there: the
website only ever writes the audit log and dbo, and a rebuild replaces dbo
from raw and the log, so that is the one check that a change lasts.
"""

import os
import pathlib
import tempfile

from django.db import connection

PROJECT = pathlib.Path(os.environ.get("DBT_TEST_PROJECT_DIR", "/dbt"))

# dbt's own files for these runs, kept out of the project folder, which the
# etl container uses too.
_WORK = pathlib.Path(tempfile.mkdtemp(prefix="dbt-test-"))


class BuildFailed(AssertionError):
    pass


def dbt(*args):
    """Run one dbt command against the database Django is connected to."""
    from dbt.cli.main import dbtRunner

    db = connection.settings_dict
    os.environ.update({
        "PGHOST": db["HOST"], "PGPORT": str(db["PORT"] or 5432),
        "PGUSER": db["USER"], "PGPASSWORD": db["PASSWORD"], "PGDATABASE": db["NAME"],
    })
    if not PROJECT.is_dir():
        raise BuildFailed(f"There is no dbt project at {PROJECT}. The web container "
                          "mounts ETL/dbt there (docker-compose.yml).")
    result = dbtRunner().invoke([
        *args, "--project-dir", str(PROJECT), "--profiles-dir", str(PROJECT),
        "--target-path", str(_WORK / "target"), "--log-path", str(_WORK / "logs"),
        "--quiet",
    ])
    if not result.success:
        problems = []
        for node in getattr(result.result, "results", None) or []:
            if str(node.status) not in ("success", "pass"):
                problems.append(f"{node.node.name}: {node.status} {node.message or ''}".strip())
        raise BuildFailed(f"dbt {' '.join(args)} failed: "
                          + ("; ".join(problems) or str(result.exception)))
    return result


def build_and_swap():
    """A full rebuild: every model and test, then the swap."""
    dbt("build")
    dbt("run-operation", "swap")
