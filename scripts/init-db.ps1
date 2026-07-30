# LWCam shared-database compatibility migration (Windows PowerShell)
# Usage: .\scripts\init-db.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$EnvFile = Join-Path $ProjectRoot ".env.local"

if (-not (Test-Path $EnvFile)) {
    throw ".env.local not found. Copy from .env.example and set DB credentials."
}

Get-Content $EnvFile | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
        $name = $matches[1].Trim()
        $value = $matches[2].Trim()
        Set-Item -Path "env:$name" -Value $value
    }
}

$env:PGPASSWORD = $env:DB_PASSWORD

function Find-Psql {
    $cmd = Get-Command psql -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $candidates = @(
        "C:\Program Files\PostgreSQL\*\bin\psql.exe",
        "C:\Program Files (x86)\PostgreSQL\*\bin\psql.exe",
        "D:\PostgreSQL\*\bin\psql.exe",
        "D:\Program Files\PostgreSQL\*\bin\psql.exe"
    )
    foreach ($pattern in $candidates) {
        $found = Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    return $null
}

$psql = Find-Psql
if (-not $psql) {
    throw "psql not found. Add PostgreSQL bin to PATH, e.g. C:\Program Files\PostgreSQL\16\bin"
}

Write-Host "Connecting to PostgreSQL as $($env:DB_USER) on $($env:DB_HOST):$($env:DB_PORT) ..."

$exists = & $psql -h $env:DB_HOST -p $env:DB_PORT -U $env:DB_USER -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$env:DB_NAME'"
if ($exists -ne "1") {
    throw "Database $($env:DB_NAME) does not exist. Import the shared LWCam schema before running this compatibility migration."
}

$migrationFiles = @(
    "001_qc_platform_deltas.sql",
    "002_role_case_normalization.sql"
)

foreach ($file in $migrationFiles) {
    Write-Host "Running migration $file ..."
    & $psql -h $env:DB_HOST -p $env:DB_PORT -U $env:DB_USER -d $env:DB_NAME -v ON_ERROR_STOP=1 -f (Join-Path $ProjectRoot "database\migrations\$file")
}

$connStr = 'postgresql://' + $env:DB_USER + '@' + $env:DB_HOST + ':' + $env:DB_PORT + '/' + $env:DB_NAME
Write-Host "Compatibility migration complete. Connection: $connStr"

