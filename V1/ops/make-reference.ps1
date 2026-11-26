#
# Freeze the local copy of the live database as `reference`, from PowerShell.
#
#     powershell -ExecutionPolicy Bypass -File ops\make-reference.ps1
#
# The same job as ops/make-reference.sh: read that script for why. Run
# ops\pull-db.ps1 first, and again after every pull.

$ErrorActionPreference = 'Continue'
Push-Location (Join-Path $PSScriptRoot '..')
try {
    $sql = @'
SELECT count(pg_terminate_backend(pid)) AS closed_connections
FROM   pg_stat_activity
WHERE  datname = 'cascadia' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS reference WITH (FORCE);
CREATE DATABASE reference TEMPLATE cascadia;
'@
    $sql | docker compose exec -T db psql -U cascadia -d postgres -v ON_ERROR_STOP=1 -q
    if ($LASTEXITCODE -ne 0) { Write-Host 'FAILED copying cascadia to reference. Is the local database up and pulled (ops\pull-db.ps1)?'; exit 1 }

    docker compose exec -T db psql -U cascadia -d reference -tAc "SELECT 'reference: ' || count(*) || ' sightings, audit log to ' || max(occurred_at)::date FROM app.sighting, (SELECT max(occurred_at) AS occurred_at FROM app.audit_log) a"
    if ($LASTEXITCODE -ne 0) { exit 1 }
} finally {
    Pop-Location
}
