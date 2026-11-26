#!/usr/bin/env bash
#
# Copy the live database onto this machine.
#
#     ops/pull-db.sh
#
# This is how you get real data locally. It takes a fresh dump from the server,
# drops whatever is in the local database and restores over it, so anything you
# were doing locally is lost. That is the point: local is scratch, the server is
# real.
#
# It signs in with the same database password you would use in DBeaver, so
# there is no SSH key to install and nothing else to set up. Set SEDB_PASSWORD
# in the environment to skip the prompt.
#
# Takes about a minute. Nothing is written to the server.
#
# Every step says what it is doing, and if one fails the script stops and says
# which one and what usually causes it, so a failure on someone else's machine
# can be read off their screen.
set -euo pipefail

HOST=${SEDB_HOST:-143.198.155.64}
REMOTE_USER=${SEDB_USER:-sedb}
REMOTE_DB=${SEDB_DB:-sedb}

# Git Bash on Windows rewrites anything that looks like a Unix path before
# handing it to a Windows program, so /tmp/sedb.dump would reach docker as
# C:/Users/.../Temp/sedb.dump and mean nothing inside the container. This turns
# that off. It does nothing anywhere else.
export MSYS_NO_PATHCONV=1

cd "$(dirname "$0")/.."

STEP="starting"
fail() {
    echo
    echo "FAILED while $STEP."
    [ -n "${1:-}" ] && echo "$1"
    exit 1
}
trap 'fail' ERR

step() {
    STEP=$1
    echo
    echo "== $1"
}

step "checking Docker"
command -v docker >/dev/null \
    || fail "docker is not on the PATH. Install Docker Desktop, and on Windows run this in Git Bash."
docker info >/dev/null 2>&1 \
    || fail "Docker is installed but not running. Start Docker Desktop, wait for it to say it is running, and try again."
# Without the Compose plugin, docker does not say compose is missing: it fails
# on the first flag after it instead, as "unknown shorthand flag: 'd' in -d".
docker compose version >/dev/null 2>&1 \
    || fail "This docker ($(command -v docker)) has no 'docker compose'. Update Docker Desktop, and
on Windows check that 'which docker' in Git Bash points into Docker Desktop's
folder and not at another copy of docker from Chocolatey, Scoop or similar."
echo "Docker is running."

if [ -z "${SEDB_PASSWORD:-}" ]; then
    read -rsp "Database password for $REMOTE_USER@$HOST: " SEDB_PASSWORD
    echo
fi
[ -n "$SEDB_PASSWORD" ] || fail "No password was entered."

step "starting the local database"
docker compose up -d db
healthy=
for _ in $(seq 1 60); do
    status=$(docker compose ps --format '{{.Health}}' db 2>/dev/null || true)
    if [ "$status" = healthy ]; then healthy=1; break; fi
    printf '.'
    sleep 2
done
echo
[ -n "$healthy" ] || fail "The local database did not become healthy within two minutes.
Its last log lines:
$(docker compose logs --tail 20 db 2>&1)"
echo "Local database is up."

# pg_dump runs inside the database container, so the only thing this machine
# needs installed is Docker. The connection is tried on its own first, because
# a wrong password or a blocked port otherwise surfaces from deep in pg_dump.
step "connecting to $HOST as $REMOTE_USER"
if ! out=$(docker compose exec -T -e PGPASSWORD="$SEDB_PASSWORD" -e PGCONNECT_TIMEOUT=15 db \
        psql -h "$HOST" -U "$REMOTE_USER" -d "$REMOTE_DB" -tAc "SELECT 'Connected, PostgreSQL ' || current_setting('server_version')" 2>&1); then
    hint="Postgres said:
$out
"
    case $out in
        *"password authentication failed"*)
            hint+="The password is wrong. It is the same one DBeaver uses for $REMOTE_USER." ;;
        *"timeout"*|*"timed out"*|*"could not connect"*|*"Connection refused"*)
            hint+="This machine cannot reach port 5432 on $HOST. A work or guest network that blocks
outgoing database traffic is the usual cause; try another network, or a phone hotspot." ;;
        *"no pg_hba.conf entry"*)
            hint+="The server is refusing connections from this machine's address. It needs adding
to pg_hba.conf on the server." ;;
    esac
    fail "$hint"
fi
echo "$out"

# pg_dump and pg_restore both have long quiet stretches that look the same as
# hung. So each runs in the background with -v, and this redraws one status
# line every second from what they have logged: which phase it is in, a bar of
# tables done out of the total once the data is moving, and the time taken.
# Their full log is shown if they fail. The line is cut to the terminal's
# width, because a line that wraps cannot be redrawn in place and each redraw
# would land on a new line instead.
LOG=$(mktemp)
trap 'rm -f "$LOG"' EXIT

progress() {  # progress PID PATTERN TOTAL BEFORE-TEXT AFTER-TEXT
    local pid=$1 pattern=$2 total=$3 before=$4 after=$5
    local done table line bar filled width=20 spin='|/-\' i=0 cols
    [ "$total" -gt 0 ] || total=1
    while kill -0 "$pid" 2>/dev/null; do
        cols=$(tput cols 2>/dev/null || echo 80)
        done=$(grep -c "$pattern" "$LOG" || true)
        if [ "$done" -eq 0 ]; then
            line="$before"
        elif [ "$done" -lt "$total" ]; then
            filled=$(( done * width / total ))
            bar=$(printf '%*s' "$filled" '' | tr ' ' '#')$(printf '%*s' $(( width - filled )) '' | tr ' ' '-')
            table=$(grep "$pattern" "$LOG" | tail -n 1 | sed 's/.*"\(.*\)".*/\1/')
            line="[$bar] $done/$total tables, now $table"
        else
            line="$after"
        fi
        line="  ${spin:i++%4:1} $(( SECONDS / 60 ))m$(printf %02d $(( SECONDS % 60 )))s  $line"
        printf '\r\033[K%s' "${line:0:cols-1}"
        sleep 1
    done
    printf '\r\033[K'
    if ! wait "$pid"; then
        echo "Its last lines:"
        tail -n 15 "$LOG"
        fail
    fi
}

# The filters keep PostGIS's optional companions out. tiger and topology are
# its geocoding and topology schemas: nothing here uses them, the sedb login
# cannot read tiger at all, and leaving postgis_topology's extension in the
# dump without its schema makes the restore fail on the way back in.
#
# Before any data moves, pg_dump reads the definition of every function in the
# database one round trip at a time, including the 900-odd that belong to
# PostGIS and never go into the dump. That is about 30 seconds over a home
# connection, with nothing logged and nothing written to the file, so the
# status line says so rather than leaving it looking stuck.
step "dumping from $HOST"
tables=$(docker compose exec -T -e PGPASSWORD="$SEDB_PASSWORD" db \
    psql -h "$HOST" -U "$REMOTE_USER" -d "$REMOTE_DB" -tAc \
    "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN
       ('pg_catalog', 'information_schema', 'tiger', 'tiger_data', 'topology')" | tr -d '[:space:]')
SECONDS=0
docker compose exec -T -e PGPASSWORD="$SEDB_PASSWORD" db \
    pg_dump -v -h "$HOST" -U "$REMOTE_USER" -d "$REMOTE_DB" -Fc --no-owner --no-acl \
            -e postgis -N tiger -N tiger_data -N topology -f /tmp/sedb.dump </dev/null >"$LOG" 2>&1 &
progress $! "dumping contents of table" "$tables" \
    "reading definitions, usually about 30s with no other sign of life" \
    "finishing the file"
echo "Dumped $tables tables, $(docker compose exec -T db du -h /tmp/sedb.dump | cut -f1), in $(( SECONDS / 60 ))m$(( SECONDS % 60 ))s."

step "restoring into the local database"
docker compose exec -T db dropdb   -U cascadia --if-exists --force cascadia
docker compose exec -T db createdb -U cascadia cascadia
tables=$(docker compose exec -T db pg_restore -l /tmp/sedb.dump | grep -c "TABLE DATA" || true)
SECONDS=0
docker compose exec -T db pg_restore -v -U cascadia -d cascadia --no-owner --no-acl /tmp/sedb.dump </dev/null >"$LOG" 2>&1 &
progress $! "processing data for table" "$tables" \
    "creating tables" \
    "building indexes and keys"
echo "Restored $tables tables in $(( SECONDS / 60 ))m$(( SECONDS % 60 ))s."
docker compose exec -T db rm -f /tmp/sedb.dump

step "checking what arrived"
docker compose exec -T db psql -U cascadia -d cascadia -tAc \
    "SELECT 'Loaded ' || count(*) || ' sightings.' FROM app.sighting"
docker compose exec -T db psql -U cascadia -d cascadia -tAc \
    "SELECT 'Logins: ' || string_agg(username, ', ' ORDER BY username) FROM public.auth_user WHERE is_active"

echo
echo "Done. Now run: docker compose up"
