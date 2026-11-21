# check-db.ps1 - is PostgreSQL usable by WORKCODE?  Read-only: nothing is installed, changed or deleted.
#
#   .\check-db.bat                                  (double-click works too)
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\check-db.ps1
#
# It answers three separate questions, because they fail for different reasons:
#   1. is a PostgreSQL running on this PC, and on which port?
#   2. do the user name and password from .env really work?  (psql, no guessing)
#   3. can a Docker CONTAINER reach it?  (this one is what the app needs - a Windows program
#      connecting fine does not prove the container can: pg_hba.conf often allows only 127.0.0.1)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $root

function Say($text) { Write-Host $text }

function Read-EnvFile($path) {
    $map = @{}
    if (Test-Path $path) {
        foreach ($line in Get-Content $path) {
            $t = $line.Trim()
            if ($t -eq '' -or $t.StartsWith('#')) { continue }
            $i = $t.IndexOf('=')
            if ($i -gt 0) {
                $key = $t.Substring(0, $i).Trim()
                $value = $t.Substring($i + 1).Trim().Trim('"')
                $map[$key] = $value
            }
        }
    }
    return $map
}

function Test-Port($port) {
    try {
        return [bool](Test-NetConnection -ComputerName 127.0.0.1 -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue)
    } catch {
        return $false
    }
}

function Find-Psql {
    $cmd = Get-Command psql -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $found = Get-ChildItem 'C:\Program Files\PostgreSQL\*\bin\psql.exe' -ErrorAction SilentlyContinue |
             Sort-Object FullName -Descending | Select-Object -First 1
    if ($found) { return $found.FullName }
    return $null
}

Say ""
Say "WORKCODE - PostgreSQL check            (folder: $root)"
Say "----------------------------------------------------------"

# ---------------------------------------------------------------- settings
$envMap = Read-EnvFile (Join-Path $root '.env')
$user = 'postgres'
$port = '5432'
$database = 'workcode_v2'
$password = ''
if ($envMap.ContainsKey('LOCAL_PGUSER'))     { $user = $envMap['LOCAL_PGUSER'] }
if ($envMap.ContainsKey('LOCAL_PGPORT'))     { $port = $envMap['LOCAL_PGPORT'] }
if ($envMap.ContainsKey('LOCAL_PGDATABASE')) { $database = $envMap['LOCAL_PGDATABASE'] }
if ($envMap.ContainsKey('LOCAL_PGPASSWORD')) { $password = $envMap['LOCAL_PGPASSWORD'] }

Say "Settings (from .env, which docker-compose reads):"
if (Test-Path (Join-Path $root '.env')) {
    Say "  .env            found"
} else {
    Say "  .env            MISSING - only Docker's own database mode works without it:"
    Say "                  copy .env.example .env  and put your PostgreSQL password in it"
}
Say ("  user            " + $user)
Say ("  port            " + $port)
Say ("  database        " + $database)
if ($password -ne '' -and $password -notlike '*change-me*') {
    Say ("  password        set, " + $password.Length + " characters")
} else {
    Say "  password        NOT set - password tests below are skipped"
    $password = ''
}

# ---------------------------------------------------------------- 1. is it running
Say ""
Say "[1] Is a PostgreSQL running on this PC?"
$services = @()
try { $services = Get-Service -Name 'postgresql*' -ErrorAction SilentlyContinue } catch { $services = @() }
if ($services) {
    foreach ($s in $services) { Say ("  service " + $s.Name + ": " + $s.Status) }
} else {
    Say "  no Windows service named postgresql* - PostgreSQL may be installed in another way"
}
foreach ($p in @('5432', '5433', '5434')) {
    if (Test-Port $p) { Say ("  port " + $p + ": open") } else { Say ("  port " + $p + ": closed") }
}

# ---------------------------------------------------------------- 2. do the credentials work
Say ""
Say "[2] Do these settings really connect? (from this PC)"
$psql = Find-Psql
if (-not $psql) {
    Say "  psql.exe not found - skipped. It is in C:\Program Files\PostgreSQL\<version>\bin"
    Say "  (pgAdmin can answer the same: register a server with the values above)"
} elseif ($password -eq '') {
    Say "  skipped - no password in .env"
} else {
    $oldPassword = $env:PGPASSWORD
    $env:PGPASSWORD = $password
    $auth = & $psql -h 127.0.0.1 -p $port -U $user -d postgres -t -A -c "select current_user;" 2>&1
    $authCode = $LASTEXITCODE
    if ($authCode -eq 0) {
        Say ("  AUTH OK - connected as " + ($auth -join ' '))
        $dbs = & $psql -h 127.0.0.1 -p $port -U $user -d postgres -t -A -c "select datname from pg_database where datistemplate = false order by 1;" 2>&1
        Say ("  databases: " + (($dbs | Where-Object { $_ -ne '' }) -join ', '))
        if (($dbs -join ' ') -like "*$database*") {
            $tables = & $psql -h 127.0.0.1 -p $port -U $user -d $database -t -A -c "select count(*) from information_schema.tables where table_schema = 'public';" 2>&1
            Say ("  " + $database + ": " + ($tables -join ' ') + " tables in schema public (43 = complete)")
            $version = & $psql -h 127.0.0.1 -p $port -U $user -d $database -t -A -c "select max(version_num) from alembic_version;" 2>&1
            Say ("  schema version: " + ($version -join ' ') + " (0010 = complete)")
        } else {
            Say ("  " + $database + ": DOES NOT EXIST yet - the first WORKCODE start creates it")
        }
    } else {
        Say ("  AUTH FAILED: " + (($auth | Where-Object { $_ -ne '' }) -join ' '))
    }
    $env:PGPASSWORD = $oldPassword
}

# ---------------------------------------------------------------- 3. can a container reach it
Say ""
Say "[3] Can a Docker container reach it? (this is what WORKCODE in Docker needs)"
$containerOk = $null
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    Say "  docker not found - skipped"
} elseif ($password -eq '') {
    Say "  skipped - no password in .env"
} else {
    $out = docker run --rm --add-host=host.docker.internal:host-gateway -e "PGPASSWORD=$password" postgres:17 `
           psql -h host.docker.internal -p $port -U $user -d postgres -t -A -c "select current_user;" 2>&1
    $code = $LASTEXITCODE
    $text = ($out | Where-Object { $_ -ne '' }) -join ' '
    if ($code -eq 0) {
        $containerOk = $true
        Say ("  CONTAINER OK - reached your PostgreSQL as " + $text)
    } else {
        $containerOk = $false
        Say ("  CONTAINER FAILED: " + $text)
        Say "  hint: 'no pg_hba.conf entry' means your PostgreSQL accepts only 127.0.0.1. Either add"
        Say "        host all all 0.0.0.0/0 scram-sha-256  to pg_hba.conf and set listen_addresses = '*'"
        Say "        in postgresql.conf, restart the service, or use Docker's own database"
        Say "        (docker compose up -d --build, no -f docker-compose.localdb.yml)."
    }
}

# ---------------------------------------------------------------- verdict
Say ""
Say "----------------------------------------------------------"
if ($password -eq '' -and -not (Test-Port '5434')) {
    Say "Next step: copy .env.example to .env, put your PostgreSQL password in it, run this file again."
} elseif ($containerOk -eq $true) {
    Say "Everything the app needs is there. Next step:"
    Say "  docker compose -f docker-compose.yml -f docker-compose.localdb.yml up -d --build"
} elseif ($containerOk -eq $false) {
    Say "[3] failed, so WORKCODE in Docker cannot use this PostgreSQL yet. Two ways:"
    Say "  a) use Docker's own database (nothing to configure):"
    Say "       docker compose up -d --build"
    Say "  b) keep your PostgreSQL: fix what [3] printed (see the hint above), then run this file again"
} else {
    Say "Next step: docker compose up -d --build   (Docker's own database, no settings needed)"
    Say "for your own PostgreSQL instead:  docker compose -f docker-compose.yml -f docker-compose.localdb.yml up -d --build"
}
Say ""
