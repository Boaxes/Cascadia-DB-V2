#!/usr/bin/env bash
#
# The steps of a run of the daily pipeline, one at a time. The workflow
# (.github/workflows/pipeline.yml) calls each from its own step, and
# ops/pipeline-local.sh calls the same ones against a local database, so what
# is tried on a laptop is what runs on GitHub.
#
#     ops/pipeline-steps.sh STEP
#
# Needs PIPELINE_DATABASE_URL (the website's database), DB167_ODBC (for import),
# and PUBLISH=true or false. What the steps learn goes in ETL/run/ (see
# ETL/pipeline_run.py); each step adds a line there saying whether it worked
# and how long it took, and that is what the report is made from.
#
# Publishing: the pipeline builds the new copy of the data beside the one the
# website is showing (the dbo_next, build_next and app_next schemas). Publishing
# is the quick final step that makes the new copy the live one (the dbt macro
# is called swap). It is done only when every test passed.
set -euo pipefail
cd "$(dirname "$0")/.."

ROOT=$PWD
RUN=$ROOT/ETL/run
DBT=$ROOT/ETL/dbt
STEPS=$RUN/steps.tsv
PUBLISH=${PUBLISH:-false}
TUNNEL_PORT=${PIPELINE_TUNNEL_PORT:-15432}
KEY=$HOME/.ssh/pipeline_key
SOCKET=$HOME/.ssh/pipeline_tunnel.sock
SKIPPED=99
# Cloudflare's tool, at one exact version (ops/pipeline-local.sh uses the same).
WRANGLER=wrangler@4.146.0

say() { echo "$*"; }
# A line the GitHub log shows in colour, and plain text anywhere else.
warn() { if [ -n "${GITHUB_ACTIONS:-}" ]; then echo "::warning::$*"; else echo "WARNING: $*"; fi; }
fail() { if [ -n "${GITHUB_ACTIONS:-}" ]; then echo "::error::$*"; else echo "ERROR: $*"; fi; return 1; }

# dbt, from its own folder, with the profile there.
dbt() { (cd "$DBT" && command dbt "$@" --profiles-dir .); }

# The last dbt build's results, kept for the report (the next dbt command
# writes over them).
build_into_run() {
    local rc=0
    dbt build --exclude package:elementary "$@" || rc=$?
    cp "$DBT/target/run_results.json" "$RUN/build_results.json" 2>/dev/null || true
    return "$rc"
}

database() {
    local exports
    exports=$(python ETL/pipeline_run.py env --shell)
    eval "$exports"
    if [ -n "${GITHUB_ACTIONS:-}" ]; then echo "::add-mask::$PGPASSWORD"; fi
}

migration() { cat "$RUN/migration" 2>/dev/null || echo unknown; }
published() { grep -q $'^publish\tok\t' "$STEPS" 2>/dev/null; }

# -----------------------------------------------------------------------------

# dbt's packages (Elementary and dbt_utils), unless they are already there.
step_deps() {
    if [ -d "$DBT/dbt_packages/elementary" ] && [ -d "$DBT/dbt_packages/dbt_utils" ]; then
        say "dbt's packages are already installed."
    else
        dbt deps
    fi
}

step_tunnel_open() {
    local target
    [ -n "${DEPLOY_KEY:-}" ] || fail "The secret DEPLOY_KEY is empty, so the pipeline cannot reach the database server."
    [ -n "${DEPLOY_HOST:-}" ] || fail "DEPLOY_HOST is empty."
    target=$(python ETL/pipeline_run.py target)
    install -d -m 700 "$HOME/.ssh"
    printf '%s\n' "$DEPLOY_KEY" > "$KEY"
    chmod 600 "$KEY"
    ssh-keyscan -H "$DEPLOY_HOST" >> "$HOME/.ssh/known_hosts" 2>/dev/null
    # The server's Postgres is not open to the internet: reach it through the
    # server's own SSH, as deploy.yml does. -M and -S let the end of the run close it by name.
    ssh -i "$KEY" -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
        -M -S "$SOCKET" -fN -L "127.0.0.1:$TUNNEL_PORT:$target" "root@$DEPLOY_HOST"
    for _ in $(seq 1 20); do
        if (exec 3<>"/dev/tcp/127.0.0.1/$TUNNEL_PORT") 2>/dev/null; then say "The tunnel to the database is open."; return 0; fi
        sleep 1
    done
    fail "The tunnel to the database did not open."
}

step_tunnel_close() {
    ssh -S "$SOCKET" -O exit "root@${DEPLOY_HOST:-none}" >/dev/null 2>&1 || true
    if command -v shred >/dev/null; then shred -u "$KEY" 2>/dev/null || true; fi
    rm -f "$KEY" "$SOCKET"
    say "The tunnel is closed and the key is removed."
}

step_check() {
    database
    python ETL/pipeline_run.py check
}

# Elementary's own tables (schema elementary), which the build's last hook fills
# with every test's result.
step_elementary_models() {
    database
    dbt run --select elementary
}

# DB167 into raw, then a check that raw matches it. Safe to run again: it
# replaces DB167's tables in raw and nothing else.
step_import() {
    database
    python ETL/import_raw.py 2>&1 | tee "$RUN/import.log"
}

# Is this database on the new pipeline? Stops with a message when it is neither
# that nor the old structure the one-time move expects.
step_detect() {
    database
    python ETL/pipeline_run.py detect
}

# The one-time move onto the new pipeline (the header of ETL/move_to_hashed_keys.py).
# Steps 1 to 3 here; step 4, the real build and publishing, are the steps after this.
step_cutover() {
    database
    if [ "$(migration)" != not_migrated ]; then
        say "This database is already on the new pipeline: the one-time move is not needed."
        return "$SKIPPED"
    fi
    say "################################################################"
    say "# THIS DATABASE HAS NEVER RUN THE NEW PIPELINE."
    say "# Doing the one-time move onto it now (ETL/move_to_hashed_keys.py):"
    say "# the audit log's entries are moved onto the new ids."
    say "################################################################"
    warn "First-time move onto the new pipeline: this run changes the audit log."
    dbt run-operation create_persistent_tables
    python ETL/move_to_hashed_keys.py inputs
    build_into_run --vars '{replay: false}'
    if [ "$PUBLISH" = true ]; then
        # The move deletes and rewrites audit log entries, so a copy of the log
        # as it is now is kept first (the README says how to put it back).
        python ETL/move_to_hashed_keys.py backup
        python ETL/move_to_hashed_keys.py audit
    else
        warn "Publishing is off: the audit log was left as it is, and the real build is not tried. The website is still on the current data."
    fi
}

step_build() {
    database
    if [ "$(migration)" = not_migrated ] && [ "$PUBLISH" != true ]; then
        say "Not done: this is the first-time move with publishing off, and the build above was its test."
        return "$SKIPPED"
    fi
    build_into_run
}

step_publish() {
    database
    if [ "$PUBLISH" != true ]; then
        say "Publishing is off for this run: the new data is built and tested, and the website is still on the current data."
        return "$SKIPPED"
    fi
    dbt run-operation swap
}

# The pipeline's documentation. After publishing, the new data is under the
# live schema names; otherwise it is still in the _next ones.
step_docs() {
    database
    if published; then dbt docs generate --vars '{schema_suffix: ""}'; else dbt docs generate; fi
}

step_elementary_report() {
    database
    (cd "$DBT" && edr report --project-dir . --profiles-dir . --target-path target/edr --open-browser false)
    rmdir "$DBT/edr_target" 2>/dev/null || true
}

# Adds this run to app.pipeline_run, and writes ETL/run/run.json for the report.
step_record() {
    database
    dbt run-operation create_persistent_tables >/dev/null || true
    python ETL/pipeline_run.py record
}

step_site() {
    database
    python ETL/site.py
}

# Cloudflare Pages: the project is made the first time, then ETL/site goes up.
# This step has Cloudflare's secrets only, not the database's.
step_upload() {
    local out
    if [ -z "${CLOUDFLARE_API_TOKEN:-}" ] || [ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]; then
        fail "The secrets CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID must both be set for the report to go online."
    fi
    if out=$(npx --yes "$WRANGLER" pages project create cascadia-pipeline --production-branch main 2>&1); then
        say "$out"
    elif grep -qi "already exist" <<<"$out"; then
        say "The Cloudflare Pages project cascadia-pipeline already exists."
    else
        echo "$out"
        return 1
    fi
    npx --yes "$WRANGLER" pages deploy ETL/site --project-name cascadia-pipeline --branch main \
        --commit-dirty=true 2>&1 | tee "$RUN/upload.log"
}

# The report's address, from the upload's output, saved with the run.
step_report_address() {
    local url
    url=$(grep -Eo 'https://[A-Za-z0-9.-]+\.pages\.dev' "$RUN/upload.log" | tail -1 || true)
    if [ -z "$url" ]; then
        warn "The report's address was not in the upload's output."
        return 0
    fi
    say "The report is online at $url"
    if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then echo "The report is online at $url" >> "$GITHUB_STEP_SUMMARY"; fi
    database
    python ETL/pipeline_run.py url "$url"
}

# -----------------------------------------------------------------------------

name=${1:-}
case "$name" in
    begin) PUBLISH=$PUBLISH python ETL/pipeline_run.py begin; exit ;;
    deps|tunnel-open|tunnel-close|check|elementary-models|import|detect|cutover|build|publish|docs|elementary-report|record|site|upload|report-address) ;;
    *) echo "usage: $0 begin|deps|tunnel-open|check|elementary-models|import|detect|cutover|build|publish|docs|elementary-report|record|site|upload|report-address|tunnel-close" >&2; exit 2 ;;
esac

mkdir -p "$RUN"
echo "== ${name}"
started=$(date +%s)
set +e
( set -euo pipefail; "step_${name//-/_}" )
rc=$?
set -e
seconds=$(( $(date +%s) - started ))
case $rc in
    0) status=ok ;;
    "$SKIPPED") status=skipped; rc=0 ;;
    *) status=failed ;;
esac
printf '%s\t%s\t%s\n' "$name" "$status" "$seconds" >> "$STEPS"
echo "-- ${name}: ${status} in ${seconds}s"
exit $rc
