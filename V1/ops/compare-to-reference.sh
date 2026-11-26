#!/usr/bin/env bash
#
# Compare the local database with `reference`, the untouched copy of live.
#
#     ops/compare-to-reference.sh
#     ops/compare-to-reference.sh --known IdentificationsBySightingV
#
# The answer to "does the new pipeline reproduce live?". Run it after a build
# has been swapped in locally (dbt build, then dbt run-operation swap):
#
#   1. structure: every column, type, default, constraint, index, view and
#      function definition, and trigger in raw, dbo and app, both databases;
#   2. rows: every table and view in dbo and app, as multisets, both ways;
#   3. app.audit_log: unchanged -- the build must never write to it.
#
# raw's four inputs that live does not have yet (species, event_code_name,
# vessel_list, track_geometry) are listed but not counted as differences.
# --known NAME reports that relation's row differences without failing on
# them, for a difference already understood. Exits 1 on anything else.
#
# Reads both databases and writes only to a throwaway third one, `compare`,
# which is dropped and made again each run.
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."

KNOWN=()
while [ $# -gt 0 ]; do
    case $1 in
        --known) KNOWN+=("$2"); shift 2 ;;
        *) echo "Unknown argument: $1"; exit 2 ;;
    esac
done
INPUTS='species|event_code_name|vessel_list|track_geometry'

psql() { docker compose exec -T db psql -U cascadia -v ON_ERROR_STOP=1 "$@"; }
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

CATALOG=$(cat <<'SQL'
WITH s AS (SELECT oid, nspname FROM pg_namespace WHERE nspname IN ('raw', 'dbo', 'app'))
SELECT line FROM (
  SELECT 'relation ' || s.nspname || '.' || c.relname || ' kind=' || c.relkind::text AS line
  FROM pg_class c JOIN s ON s.oid = c.relnamespace WHERE c.relkind IN ('r','v','m','p','f','S')
  UNION ALL
  SELECT 'column ' || s.nspname || '.' || c.relname || '.' || a.attname || ' ' || format_type(a.atttypid, a.atttypmod)
         || CASE WHEN a.attnotnull THEN ' not null' ELSE '' END
         || coalesce(' default ' || pg_get_expr(d.adbin, d.adrelid), '')
         || CASE WHEN a.attidentity::text <> '' THEN ' identity' ELSE '' END
  FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid JOIN s ON s.oid = c.relnamespace
  LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
  WHERE a.attnum > 0 AND NOT a.attisdropped AND c.relkind IN ('r','v','m','p','f')
  UNION ALL
  SELECT 'constraint ' || s.nspname || '.' || c.relname || ' ' || k.conname || ': ' || pg_get_constraintdef(k.oid)
  FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid JOIN s ON s.oid = c.relnamespace
  UNION ALL
  SELECT 'index ' || pg_get_indexdef(i.indexrelid)
  FROM pg_index i JOIN pg_class c ON c.oid = i.indrelid JOIN s ON s.oid = c.relnamespace
  UNION ALL
  SELECT 'view ' || s.nspname || '.' || c.relname || ' md5=' || md5(pg_get_viewdef(c.oid, true))
  FROM pg_class c JOIN s ON s.oid = c.relnamespace WHERE c.relkind IN ('v','m')
  UNION ALL
  SELECT 'trigger ' || pg_get_triggerdef(t.oid)
  FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid JOIN s ON s.oid = c.relnamespace WHERE NOT t.tgisinternal
  UNION ALL
  SELECT 'function ' || s.nspname || '.' || p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ') md5=' || md5(pg_get_functiondef(p.oid))
  FROM pg_proc p JOIN s ON s.oid = p.pronamespace
  WHERE p.prokind IN ('f','p') AND NOT EXISTS (SELECT 1 FROM pg_depend dp WHERE dp.objid = p.oid AND dp.deptype = 'e')
) x ORDER BY line;
SQL
)

echo "== structure"
for db in reference cascadia; do
    echo "$CATALOG" | psql -d "$db" -At > "$WORK/$db.txt"
done
diff "$WORK/reference.txt" "$WORK/cascadia.txt" > "$WORK/structure.diff" || true
inputs=$(grep -cE "^[<>] .*raw\.(\"?)($INPUTS)\b|raw\.($INPUTS)_" "$WORK/structure.diff" || true)
grep -vE "raw\.(\"?)($INPUTS)\b|raw\.($INPUTS)_" "$WORK/structure.diff" | grep '^[<>]' > "$WORK/structure.real" || true
structure=$(wc -l < "$WORK/structure.real" | tr -d ' ')
echo "$(wc -l < "$WORK/reference.txt" | tr -d ' ') catalog lines in reference, $(wc -l < "$WORK/cascadia.txt" | tr -d ' ') locally"
echo "$inputs lines for raw's new inputs (not counted)"
echo "$structure differences  (< reference only, > local only)"
sed 's/^/  /' "$WORK/structure.real" | cut -c1-200

echo
echo "== rows"
psql -d postgres -qc "DROP DATABASE IF EXISTS compare WITH (FORCE)" -c "CREATE DATABASE compare" >/dev/null
psql -d compare -q >/dev/null <<'SQL'
CREATE EXTENSION postgis;
CREATE EXTENSION postgres_fdw;
CREATE SERVER live FOREIGN DATA WRAPPER postgres_fdw OPTIONS (dbname 'reference', host 'localhost', port '5432');
CREATE SERVER built FOREIGN DATA WRAPPER postgres_fdw OPTIONS (dbname 'cascadia', host 'localhost', port '5432');
CREATE USER MAPPING FOR CURRENT_USER SERVER live OPTIONS (user 'cascadia', password 'cascadia');
CREATE USER MAPPING FOR CURRENT_USER SERVER built OPTIONS (user 'cascadia', password 'cascadia');
CREATE SCHEMA live_dbo; CREATE SCHEMA live_app; CREATE SCHEMA built_dbo; CREATE SCHEMA built_app;
IMPORT FOREIGN SCHEMA dbo FROM SERVER live INTO live_dbo;
IMPORT FOREIGN SCHEMA app FROM SERVER live INTO live_app;
IMPORT FOREIGN SCHEMA dbo FROM SERVER built INTO built_dbo;
IMPORT FOREIGN SCHEMA app FROM SERVER built INTO built_app;
CREATE TABLE result (layer text, name text, rows bigint, only_live bigint, only_built bigint);
DO $$
DECLARE t record; a bigint; b bigint; n bigint;
BEGIN
  FOR t IN SELECT 'dbo' AS layer, relname FROM pg_class WHERE relnamespace = 'live_dbo'::regnamespace
           UNION ALL SELECT 'app', relname FROM pg_class WHERE relnamespace = 'live_app'::regnamespace
  LOOP
    IF to_regclass(format('built_%s.%I', t.layer, t.relname)) IS NULL THEN
      INSERT INTO result VALUES (t.layer, t.relname, NULL, NULL, NULL);
      CONTINUE;
    END IF;
    EXECUTE format('CREATE TEMP TABLE l AS SELECT * FROM live_%s.%I', t.layer, t.relname);
    EXECUTE format('CREATE TEMP TABLE b AS SELECT * FROM built_%s.%I', t.layer, t.relname);
    SELECT count(*) INTO n FROM l;
    SELECT count(*) INTO a FROM (SELECT * FROM l EXCEPT ALL SELECT * FROM b) x;
    SELECT count(*) INTO b FROM (SELECT * FROM b EXCEPT ALL SELECT * FROM l) y;
    INSERT INTO result VALUES (t.layer, t.relname, n, a, b);
    DROP TABLE l; DROP TABLE b;
  END LOOP;
END $$;
SQL
psql -d compare -At -F ' | ' -c "SELECT layer, count(*), sum(rows) FROM result GROUP BY 1 ORDER BY 1" \
    | awk -F' \\| ' '{printf "%s: %s relations, %s rows compared\n", $1, $2, $3}'
psql -d compare -At -F '|' -c "SELECT layer || '.' || name, coalesce(only_live::text, 'missing'), coalesce(only_built::text, 'missing') FROM result WHERE only_live IS DISTINCT FROM 0 OR only_built IS DISTINCT FROM 0 ORDER BY 1" > "$WORK/rows.txt"
rows=0
while IFS='|' read -r name live built; do
    [ -z "$name" ] && continue
    tag=""
    for k in "${KNOWN[@]:-}"; do [ -n "$k" ] && [ "${name#*.}" = "$k" ] && tag="  (known)"; done
    echo "  $name: $live rows only in reference, $built only locally$tag"
    [ -z "$tag" ] && rows=$((rows + 1))
done < "$WORK/rows.txt"
echo "$rows relations with unexpected row differences"

audit=$(psql -d compare -At -c "SELECT (SELECT count(*) FROM (SELECT * FROM live_app.audit_log EXCEPT ALL SELECT * FROM built_app.audit_log) x) + (SELECT count(*) FROM (SELECT * FROM built_app.audit_log EXCEPT ALL SELECT * FROM live_app.audit_log) y)")
echo
echo "== app.audit_log: $([ "$audit" = 0 ] && echo unchanged || echo "$audit rows differ")"
psql -d postgres -qc "DROP DATABASE compare WITH (FORCE)" >/dev/null

echo
if [ "$structure" = 0 ] && [ "$rows" = 0 ] && [ "$audit" = 0 ]; then
    echo "MATCHES live."
else
    echo "DIFFERS from live: $structure structure, $rows relations' rows, audit log $audit."
    exit 1
fi
