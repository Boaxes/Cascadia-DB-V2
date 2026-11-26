"""
Parse the project with the checks dbt v2 will enforce, which dbt 1.x skips here.

dbt 1.x validates project and property files against the stricter spec that v2
requires -- no unknown keys, `+` on every dbt_project.yml config -- and reports
each violation as a deprecation. But it only does so for BigQuery, Databricks,
Redshift and Snowflake (`_JSONSCHEMA_SUPPORTED_ADAPTERS` in
dbt/jsonschemas/jsonschemas.py), never for Postgres. This turns the same checks
on for Postgres and fails on any violation, since dbt_project.yml makes every
deprecation an error. A project that passes is ready to move to v2 as soon as v2
has a Postgres adapter.

    docker compose run --rm etl python dbt/strict_parse.py
"""

import sys

import dbt.jsonschemas.jsonschemas as jsonschemas
from dbt.cli.main import dbtRunner

jsonschemas._JSONSCHEMA_SUPPORTED_ADAPTERS = {
    *jsonschemas._JSONSCHEMA_SUPPORTED_ADAPTERS, "postgres"}

result = dbtRunner().invoke(["parse", "--no-partial-parse", "--show-all-deprecations"])
sys.exit(0 if result.success else 1)
