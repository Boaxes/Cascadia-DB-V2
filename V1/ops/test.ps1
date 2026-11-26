#
# Run the tests, from PowerShell on Windows.
#
#     powershell -ExecutionPolicy Bypass -File ops\test.ps1 unit
#     powershell -ExecutionPolicy Bypass -File ops\test.ps1 reference
#     powershell -ExecutionPolicy Bypass -File ops\test.ps1 all
#
# The same as ops/test.sh: `unit` needs no database and is what CI runs;
# `reference` copies the local database (as ops\make-reference.ps1 does) and
# runs the tests that need real data against that copy. With no argument it
# says this and runs nothing.

param([string]$Set = '')

$ErrorActionPreference = 'Continue'
Push-Location (Join-Path $PSScriptRoot '..')

function Start-Web {
    docker compose up -d db web | Out-Null
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

function Invoke-Unit {
    Start-Web
    docker compose exec web python manage.py test unit_tests --settings=config.unit_settings
    return $LASTEXITCODE
}

function Invoke-Reference {
    Start-Web
    & (Join-Path $PSScriptRoot 'make-reference.ps1')
    if ($LASTEXITCODE -ne 0) { return 1 }
    docker compose exec web python manage.py test TESTS
    return $LASTEXITCODE
}

try {
    switch ($Set) {
        'unit'      { $code = Invoke-Unit }
        'reference' { $code = Invoke-Reference }
        'all'       { $code = Invoke-Unit; if ($code -eq 0) { $code = Invoke-Reference } }
        default {
            Write-Host 'usage: ops\test.ps1 unit | reference | all'
            Write-Host '  unit       no database; the set CI runs before every deploy'
            Write-Host '  reference  against a fresh copy of your local database'
            Write-Host '  all        both'
            $code = 0
        }
    }
} finally {
    Pop-Location
}
exit $code
