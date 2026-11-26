#!/usr/bin/env bash
#
# Build the pipeline's site (ETL/site.py) and serve it locally with Cloudflare
# Pages' own runtime, as it will be served once deployed.
#
#     ops/pipeline-site.sh [database]       # default test_today; open http://localhost:8788
#
# It reads the last run in that database: dbt's documentation and Elementary's
# report are generated from it, and ETL/verify/reports holds the latest
# verification. The daily workflow (.github/workflows/pipeline.yml) puts the same
# folder online; ops/pipeline-local.sh runs the whole pipeline locally first.
set -euo pipefail
cd "$(dirname "$0")/.."
DB=${1:-test_today}

etl() { docker compose --profile etl run --rm -T -w /app/dbt -e PGDATABASE="$DB" -e PIPELINE_DATABASE_URL="postgresql://cascadia:cascadia@db:5432/$DB" etl "$@"; }

echo "== dbt documentation, from the swapped-in build in $DB"
etl dbt docs generate --profiles-dir . --vars '{schema_suffix: ""}' | tail -1
echo "== Elementary's report"
etl edr report --project-dir . --profiles-dir . --target-path /app/dbt/target/edr --open-browser false | tail -1
etl sh -c "rmdir edr_target 2>/dev/null; cd /app && python site.py"
echo "== serving ETL/site at http://localhost:8788 (Ctrl-C to stop)"
# From the site folder, so wrangler does not read the repository's .env.
cd ETL/site && exec npx --yes wrangler@4 pages dev . --port 8788
