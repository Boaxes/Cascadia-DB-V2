#!/usr/bin/env bash
#
# What DB167 already holds is not replayed, and nothing the website made and
# deleted comes back. Builds a database twice (and once more) with entries
# written into its audit log, and checks dbo after each build.
#
#     ETL/verify/applied_entries_replay.sh [database]      # default test_today
#
# The database needs a finished build (dbt build, then swap) and the website's
# tables. It writes entries by "replay-check" into app.audit_log, and changes
# two raw values, and puts everything back when it ends.
#
#   A  a track the website made, then deleted           gone after every build
#   B  the same with an update and a match in between   gone after every build
#   C  a sighting's Comments (DB167 holds it) and depth_m (DB167 has no column
#      for it); DB167 then changes Comments               DB167's Comments, the website's depth_m
#   D  a field of an effort DB167 holds, changed later    DB167's later value
#   E  one entry, Locality held by DB167, Region not yet  Region replayed, Locality never
#   F  a track the website made and matched to an Effort that DB167 has since
#      renumbered (the entry's EffortID names no Effort now)  still matched to that Effort
set -euo pipefail
cd "$(dirname "$0")/../.."

DB=${1:-test_today}
psql_() { docker exec -i cascadia-db-1 psql -U cascadia -d "$DB" -v ON_ERROR_STOP=1 -q -At "$@"; }
build() {
    docker run --rm --network cascadia_default -v "$PWD/ETL:/app" -w /app/dbt -e PGHOST=db -e PGDATABASE="$DB" \
        cascadia-etl dbt build --profiles-dir . --exclude package:elementary > "ETL/verify/reports/replay_build_$1.log" 2>&1 \
        || { tail -20 "ETL/verify/reports/replay_build_$1.log"; echo "build $1 failed"; exit 1; }
    grep -E "Audit log entries" "ETL/verify/reports/replay_build_$1.log" | sed 's/^.*Audit/Audit/' || true
}
failed=0
check() {   # check "what" "sql giving one value" "expected"
    local got; got=$(psql_ -c "$2")
    if [ "$got" = "$3" ]; then echo "  ok    $1"; else echo "  FAIL  $1: got '$got', wanted '$3'"; failed=1; fi
}
mkdir -p ETL/verify/reports

# Two quiet rows to change: a sighting with Comments, and an effort with
# Locality and Region, that no audit log entry is about.
SIGHTING=$(psql_ -c "select \"SightingID\" from raw.\"SightingT\" r where btrim(\"Comments\") <> '' and not exists
    (select 1 from app.audit_log a where a.target_table = 'SightingT' and a.legacy_pk = r.\"SightingID\"::text) order by 1 limit 1")
read -r EFFORT LOCALITY < <(psql_ -F ' ' -c "select \"DailyEffortID\", replace(\"Locality\", ' ', '_') from raw.\"DailyEffortT\" r
    where btrim(\"Locality\") <> '' and btrim(\"Region\") <> '' and not exists
    (select 1 from app.audit_log a where a.target_table = 'DailyEffortT' and a.legacy_pk = r.\"DailyEffortID\"::text) order by 1 limit 1")
SIGHTING_COMMENTS=$(psql_ -c "select \"Comments\" from raw.\"SightingT\" where \"SightingID\" = $SIGHTING")
EFFORT_LOCALITY=$(psql_ -c "select \"Locality\" from raw.\"DailyEffortT\" where \"DailyEffortID\" = $EFFORT")
EFFORT_REGION=$(psql_ -c "select \"Region\" from raw.\"DailyEffortT\" where \"DailyEffortID\" = $EFFORT")
SIGHTING_HASH=$(psql_ -c "select id from dbo.\"SightingT\" where \"SightingID\" = $SIGHTING")
EFFORT_HASH=$(psql_ -c "select id from dbo.\"DailyEffortT\" where \"DailyEffortID\" = $EFFORT")
echo "sighting $SIGHTING, effort $EFFORT"

put_back() {
    psql_ <<SQL >/dev/null || true
alter table raw."SightingT" disable trigger "SightingT_frozen";
alter table raw."DailyEffortT" disable trigger "DailyEffortT_frozen";
update raw."SightingT" set "Comments" = \$a\$$SIGHTING_COMMENTS\$a\$ where "SightingID" = $SIGHTING;
update raw."DailyEffortT" set "Locality" = \$a\$$EFFORT_LOCALITY\$a\$ where "DailyEffortID" = $EFFORT;
alter table raw."SightingT" enable trigger "SightingT_frozen";
alter table raw."DailyEffortT" enable trigger "DailyEffortT_frozen";
delete from app.audit_log where actor_name = 'replay-check';
SQL
}
trap put_back EXIT
put_back

psql_ <<SQL
-- A: made, then deleted
insert into app.audit_log (actor_name, action, target_table, target_pk, changes) values
  ('replay-check', 'create', 'TrackT', '9000001',
   '{"TrackID": {"old": null, "new": 9000001}, "TrackFileName": {"old": null, "new": "replay-a.csv"}, "Useable": {"old": null, "new": true}}');
insert into app.audit_log (actor_name, action, target_table, target_pk, snapshot) values
  ('replay-check', 'delete', 'TrackT', '9000001',
   '{"TrackT": [{"TrackID": 9000001, "TrackFileName": "replay-a.csv", "Useable": true}], "__order__": []}');
-- B: made, changed, matched, deleted
insert into app.audit_log (actor_name, action, target_table, target_pk, changes) values
  ('replay-check', 'create', 'TrackT', '9000002',
   '{"TrackID": {"old": null, "new": 9000002}, "TrackFileName": {"old": null, "new": "replay-b.csv"}, "Useable": {"old": null, "new": true}}'),
  ('replay-check', 'update', 'TrackT', '9000002', '{"Comments": {"old": null, "new": "a note"}}'),
  ('replay-check', 'associate', 'TrackT', '9000002', '{"EffortID": {"old": null, "new": $EFFORT}}');
insert into app.audit_log (actor_name, action, target_table, target_pk, snapshot) values
  ('replay-check', 'delete', 'TrackT', '9000002',
   '{"TrackT": [{"TrackID": 9000002, "TrackFileName": "replay-b.csv", "Useable": true, "Comments": "a note", "EffortID": $EFFORT}], "__order__": []}');
-- C: Comments DB167 holds, depth_m only the website holds
insert into app.audit_log (actor_name, action, target_table, target_pk, legacy_pk, changes) values
  ('replay-check', 'update', 'SightingT', '$SIGHTING_HASH', '$SIGHTING',
   jsonb_build_object('Comments', jsonb_build_object('old', 'an older comment', 'new', \$a\$$SIGHTING_COMMENTS\$a\$),
                      'depth_m', jsonb_build_object('old', null, 'new', 77.7)));
-- D and E: Locality is held by DB167; Region is not yet
insert into app.audit_log (actor_name, action, target_table, target_pk, legacy_pk, changes) values
  ('replay-check', 'update', 'DailyEffortT', '$EFFORT_HASH', '$EFFORT',
   jsonb_build_object('Locality', jsonb_build_object('old', 'an older place', 'new', \$a\$$EFFORT_LOCALITY\$a\$),
                      'Region', jsonb_build_object('old', \$a\$$EFFORT_REGION\$a\$, 'new', 'Replay Check Region')));
-- F: made and matched to an Effort, whose number DB167 has since changed. The
-- entry keeps the Effort's hashed id (daily_effort_id), which a renumber does
-- not change, and the old number (EffortID), which names no Effort now. DB167
-- holds no row for the track, so the entry has no map of fields.
insert into app.audit_log (actor_name, action, target_table, target_pk, changes) values
  ('replay-check', 'create', 'TrackT', '9000003',
   jsonb_build_object('TrackID', jsonb_build_object('old', null, 'new', 9000003),
                      'TrackFileName', jsonb_build_object('old', null, 'new', 'replay-f.csv'),
                      'file_name', jsonb_build_object('old', null, 'new', 'replay-f.csv'),
                      'Useable', jsonb_build_object('old', null, 'new', true),
                      'EffortID', jsonb_build_object('old', null, 'new', 8999999),
                      'daily_effort_id', jsonb_build_object('old', null, 'new', '$EFFORT_HASH'::bigint)));
SQL

echo "== build 1"
build 1
check "A gone" "select count(*) from dbo_next.\"TrackT\" where \"TrackID\" = 9000001" 0
check "B gone" "select count(*) from dbo_next.\"TrackT\" where \"TrackID\" = 9000002" 0
check "C Comments is the entry's (DB167's)" "select \"Comments\" from dbo_next.\"SightingT\" where \"SightingID\" = $SIGHTING" "$SIGHTING_COMMENTS"
check "C depth_m is the website's" "select depth_m from dbo_next.\"SightingT\" where \"SightingID\" = $SIGHTING" 77.70
check "E Region is the website's" "select \"Region\" from dbo_next.\"DailyEffortT\" where \"DailyEffortID\" = $EFFORT" "Replay Check Region"
check "F keeps its Effort" "select e.\"DailyEffortID\" from dbo_next.\"TrackT\" t join dbo_next.\"DailyEffortT\" e on e.id = t.daily_effort_id where t.\"TrackID\" = 9000003" "$EFFORT"
check "C is applied" "select db167_fields ->> 'Comments' from app.audit_log where actor_name = 'replay-check' and target_table = 'SightingT'" applied
check "E: Locality applied, Region pending" "select (db167_fields ->> 'Locality') || ' ' || (db167_fields ->> 'Region') from app.audit_log where actor_name = 'replay-check' and target_table = 'DailyEffortT'" "applied pending"
check "A and B are not applicable" "select string_agg(distinct db167_state, ',') from app.audit_log where actor_name = 'replay-check' and target_table = 'TrackT' and target_pk <> '9000003'" not_applicable

# DB167 changes the two values the entries set.
psql_ <<SQL
alter table raw."SightingT" disable trigger "SightingT_frozen";
alter table raw."DailyEffortT" disable trigger "DailyEffortT_frozen";
update raw."SightingT" set "Comments" = 'DB167 changed this later' where "SightingID" = $SIGHTING;
update raw."DailyEffortT" set "Locality" = 'DB167 Changed This Place' where "DailyEffortID" = $EFFORT;
alter table raw."SightingT" enable trigger "SightingT_frozen";
alter table raw."DailyEffortT" enable trigger "DailyEffortT_frozen";
SQL

for n in 2 3; do
    echo "== build $n"
    build "$n"
    check "A gone" "select count(*) from dbo_next.\"TrackT\" where \"TrackID\" = 9000001" 0
    check "B gone" "select count(*) from dbo_next.\"TrackT\" where \"TrackID\" = 9000002" 0
    check "C Comments is DB167's later value, not the website's older one" "select \"Comments\" from dbo_next.\"SightingT\" where \"SightingID\" = $SIGHTING" "DB167 changed this later"
    check "C depth_m is still the website's" "select depth_m from dbo_next.\"SightingT\" where \"SightingID\" = $SIGHTING" 77.70
    check "D Locality is DB167's later value" "select \"Locality\" from dbo_next.\"DailyEffortT\" where \"DailyEffortID\" = $EFFORT" "DB167 Changed This Place"
    check "E Region is still the website's" "select \"Region\" from dbo_next.\"DailyEffortT\" where \"DailyEffortID\" = $EFFORT" "Replay Check Region"
    check "F keeps its Effort" "select e.\"DailyEffortID\" from dbo_next.\"TrackT\" t join dbo_next.\"DailyEffortT\" e on e.id = t.daily_effort_id where t.\"TrackID\" = 9000003" "$EFFORT"
    check "C stays applied" "select db167_state from app.audit_log where actor_name = 'replay-check' and target_table = 'SightingT'" applied
done

if [ "$failed" = 0 ]; then echo "all passed"; else echo "FAILED"; exit 1; fi
