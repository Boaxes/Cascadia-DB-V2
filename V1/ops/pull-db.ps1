#
# Copy the live database onto this machine, from PowerShell on Windows.
#
#     powershell -ExecutionPolicy Bypass -File ops\pull-db.ps1
#
# The same job as ops/pull-db.sh, step for step, for a Windows machine where
# 'docker compose' works in PowerShell but not in Git Bash. Read that script
# for why each step is there; this one only notes where PowerShell differs.
#
# It takes a fresh dump from the server, drops whatever is in the local
# database and restores over it, so anything you were doing locally is lost.
# Set SEDB_PASSWORD in the environment to skip the password prompt.
#
# -ExecutionPolicy Bypass is there because Windows refuses to run downloaded
# scripts by default. It applies to this one run and changes no setting.
#
# Written for the Windows PowerShell 5.1 that comes with Windows, so nothing
# here needs PowerShell 7.

# Stop would turn every line a native program writes to stderr into a
# terminating error, and docker writes its progress there. Each docker call is
# checked by its exit code instead.
$ErrorActionPreference = 'Continue'

$DbHost = if ($env:SEDB_HOST) { $env:SEDB_HOST } else { '143.198.155.64' }
$RemoteUser = if ($env:SEDB_USER) { $env:SEDB_USER } else { 'sedb' }
$RemoteDb = if ($env:SEDB_DB) { $env:SEDB_DB } else { 'sedb' }

Push-Location (Join-Path $PSScriptRoot '..')

$script:Step = 'starting'
function Fail([string]$Message) {
    Write-Host ''
    Write-Host "FAILED while $script:Step."
    if ($Message) { Write-Host $Message }
    exit 1
}

function Step([string]$Name) {
    $script:Step = $Name
    Write-Host ''
    Write-Host "== $Name"
}

function Check([string]$Message) {
    if ($LASTEXITCODE -ne 0) { Fail $Message }
}

# Read a log that another process still has open for writing.
function Read-Log([string]$Path) {
    try {
        $stream = [IO.File]::Open($Path, 'Open', 'Read', 'ReadWrite')
        $reader = New-Object IO.StreamReader($stream)
        try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
    } catch {
        return ''
    }
}

$Log = [IO.Path]::GetTempFileName()
$OutLog = [IO.Path]::GetTempFileName()
$NoInput = [IO.Path]::GetTempFileName()

# Runs docker in the background and redraws one status line a second from what
# it has logged, as progress() does in pull-db.sh. The line is padded rather
# than cleared with an escape code, which the old Windows console ignores.
function Invoke-WithProgress([string[]]$DockerArgs, [string]$Pattern, [int]$Total, [string]$Before, [string]$After) {
    if ($Total -le 0) { $Total = 1 }
    $width = 20
    $spin = '|/-\'
    $i = 0
    $cols = 80
    $clock = [Diagnostics.Stopwatch]::StartNew()
    # These arguments reach docker joined by spaces with no quoting, which is
    # safe only because none of them contains a space. The password is not
    # among them: docker copies PGPASSWORD from this process's environment.
    $proc = Start-Process -FilePath docker -ArgumentList $DockerArgs -NoNewWindow -PassThru `
        -RedirectStandardError $Log -RedirectStandardOutput $OutLog -RedirectStandardInput $NoInput
    # Without touching Handle, ExitCode stays empty once the process is gone.
    $null = $proc.Handle
    while (-not $proc.HasExited) {
        try { $cols = $Host.UI.RawUI.WindowSize.Width } catch { }
        $hits = @((Read-Log $Log) -split "`r?`n" | Where-Object { $_ -like "*$Pattern*" })
        $done = $hits.Count
        if ($done -eq 0) {
            $line = $Before
        } elseif ($done -lt $Total) {
            $filled = [math]::Floor($done * $width / $Total)
            $bar = ('#' * $filled) + ('-' * ($width - $filled))
            $table = if ($hits[-1] -match '"(.*)"') { $Matches[1] } else { '' }
            $line = "[$bar] $done/$Total tables, now $table"
        } else {
            $line = $After
        }
        $elapsed = $clock.Elapsed
        $line = '  {0} {1}m{2:00}s  {3}' -f $spin[$i % 4], [int][math]::Floor($elapsed.TotalMinutes), $elapsed.Seconds, $line
        $i++
        if ($line.Length -gt $cols - 1) { $line = $line.Substring(0, $cols - 1) }
        Write-Host -NoNewline ("`r" + $line.PadRight($cols - 1))
        Start-Sleep -Seconds 1
    }
    $proc.WaitForExit()
    Write-Host -NoNewline ("`r" + (' ' * ($cols - 1)) + "`r")
    if ($proc.ExitCode -ne 0) {
        Write-Host 'Its last lines:'
        ((Read-Log $OutLog) + (Read-Log $Log)) -split "`r?`n" | Select-Object -Last 15 | Write-Host
        Fail
    }
    return $clock.Elapsed
}

function Format-Elapsed([TimeSpan]$Elapsed) {
    '{0}m{1}s' -f [int][math]::Floor($Elapsed.TotalMinutes), $Elapsed.Seconds
}

try {
    Step 'checking Docker'
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Fail 'docker is not on the PATH. Install Docker Desktop.'
    }
    docker info *> $null
    Check 'Docker is installed but not running. Start Docker Desktop, wait for it to say it is running, and try again.'
    docker compose version *> $null
    Check "This docker ($((Get-Command docker).Source)) has no 'docker compose'. Update Docker Desktop."
    Write-Host 'Docker is running.'

    # docker is told the variable's name only, -e PGPASSWORD, and takes the
    # value from here. Windows PowerShell mangles quotes inside arguments it
    # passes to other programs, so a password is never put on a command line.
    if ($env:SEDB_PASSWORD) {
        $env:PGPASSWORD = $env:SEDB_PASSWORD
    } else {
        $secure = Read-Host "Database password for $RemoteUser@$DbHost" -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try {
            $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        } finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        }
    }
    if (-not $env:PGPASSWORD) { Fail 'No password was entered.' }

    Step 'starting the local database'
    docker compose up -d db
    Check
    $healthy = $false
    for ($n = 0; $n -lt 60; $n++) {
        $status = docker compose ps --format '{{.Health}}' db 2>$null
        if ("$status".Trim() -eq 'healthy') { $healthy = $true; break }
        Write-Host -NoNewline '.'
        Start-Sleep -Seconds 2
    }
    Write-Host ''
    if (-not $healthy) {
        $logs = (docker compose logs --tail 20 db 2>&1 | ForEach-Object { "$_" }) -join "`n"
        Fail "The local database did not become healthy within two minutes.`nIts last log lines:`n$logs"
    }
    Write-Host 'Local database is up.'

    Step "connecting to $DbHost as $RemoteUser"
    $out = (docker compose exec -T -e PGPASSWORD -e PGCONNECT_TIMEOUT=15 db `
        psql -h $DbHost -U $RemoteUser -d $RemoteDb -tAc "SELECT 'Connected, PostgreSQL ' || current_setting('server_version')" 2>&1 |
        ForEach-Object { "$_" }) -join "`n"
    if ($LASTEXITCODE -ne 0) {
        $hint = "Postgres said:`n$out`n"
        if ($out -like '*password authentication failed*') {
            $hint += "The password is wrong. It is the same one DBeaver uses for $RemoteUser."
        } elseif ($out -like '*timeout*' -or $out -like '*timed out*' -or $out -like '*could not connect*' -or $out -like '*Connection refused*') {
            $hint += "This machine cannot reach port 5432 on $DbHost. A work or guest network that blocks`noutgoing database traffic is the usual cause; try another network, or a phone hotspot."
        } elseif ($out -like '*no pg_hba.conf entry*') {
            $hint += "The server is refusing connections from this machine's address. It needs adding`nto pg_hba.conf on the server."
        }
        Fail $hint
    }
    Write-Host $out

    Step "dumping from $DbHost"
    $tables = docker compose exec -T -e PGPASSWORD db psql -h $DbHost -U $RemoteUser -d $RemoteDb -tAc `
        "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema', 'tiger', 'tiger_data', 'topology')"
    Check
    $tables = "$tables".Trim()
    $took = Invoke-WithProgress @('compose', 'exec', '-T', '-e', 'PGPASSWORD', 'db',
            'pg_dump', '-v', '-h', $DbHost, '-U', $RemoteUser, '-d', $RemoteDb, '-Fc', '--no-owner', '--no-acl',
            '-e', 'postgis', '-N', 'tiger', '-N', 'tiger_data', '-N', 'topology', '-f', '/tmp/sedb.dump') `
        'dumping contents of table' ([int]$tables) `
        'reading definitions, usually about 30s with no other sign of life' `
        'finishing the file'
    $size = ("$(docker compose exec -T db du -h /tmp/sedb.dump)" -split "\s+")[0]
    Write-Host "Dumped $tables tables, $size, in $(Format-Elapsed $took)."

    Step 'restoring into the local database'
    docker compose exec -T db dropdb -U cascadia --if-exists --force cascadia
    Check
    docker compose exec -T db createdb -U cascadia cascadia
    Check
    $tables = @(docker compose exec -T db pg_restore -l /tmp/sedb.dump | Where-Object { $_ -like '*TABLE DATA*' }).Count
    $took = Invoke-WithProgress @('compose', 'exec', '-T', 'db',
            'pg_restore', '-v', '-U', 'cascadia', '-d', 'cascadia', '--no-owner', '--no-acl', '/tmp/sedb.dump') `
        'processing data for table' $tables `
        'creating tables' `
        'building indexes and keys'
    Write-Host "Restored $tables tables in $(Format-Elapsed $took)."
    docker compose exec -T db rm -f /tmp/sedb.dump
    Check

    Step 'checking what arrived'
    docker compose exec -T db psql -U cascadia -d cascadia -tAc "SELECT 'Loaded ' || count(*) || ' sightings.' FROM app.sighting"
    Check
    docker compose exec -T db psql -U cascadia -d cascadia -tAc "SELECT 'Logins: ' || string_agg(username, ', ' ORDER BY username) FROM public.auth_user WHERE is_active"
    Check

    Write-Host ''
    Write-Host 'Done. Now run: docker compose up'
} finally {
    Pop-Location
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    Remove-Item $Log, $OutLog, $NoInput -ErrorAction SilentlyContinue
}
