#!/usr/bin/env bash
#
# Run the tests.
#
#     ops/test.sh unit        no database; the set CI runs before every deploy
#     ops/test.sh reference   against a fresh copy of your local database
#     ops/test.sh all         both
#
# With no argument it says this and runs nothing. `reference` copies whatever
# ops/pull-db.sh last put in the local database (the same copy
# ops/make-reference.sh makes), so pull first if you want the live data as it
# is now. Nothing is written to the server, and the tests work on their own
# copy, never on the database the website uses.
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."

# `up -d` leaves a running web container alone and recreates it when
# docker-compose.yml has changed since it was made.
web() { docker compose up -d db web >/dev/null; }

unit() {
    web
    docker compose exec web python manage.py test unit_tests --settings=config.unit_settings
}

reference() {
    web
    ops/make-reference.sh
    docker compose exec web python manage.py test TESTS
}

case "${1:-}" in
  unit)      unit ;;
  reference) reference ;;
  all)       unit; reference ;;
  *)         sed -n '3,14p' "$0" | sed 's/^# \{0,1\}//' ;;
esac
