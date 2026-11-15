# KB-Assistant uninstall helper.
# Runs BEFORE the NSIS uninstaller removes any file (or as the Tauri NSIS
# PREUNINSTALL hook). It stops the resident processes and optionally protects
# the user's knowledge base data.
param(
    [string]$InstallDir = "",
    [switch]$KeepData
)

$ErrorActionPreference = 'SilentlyContinue'

if ([string]::IsNullOrEmpty($InstallDir)) {
    $InstallDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
Write-Host "[KB-Assistant] InstallDir: $InstallDir"

# 1) Stop the tray-resident desktop app so its files are not locked.
Get-Process -Name 'kb-assistant' -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "[KB-Assistant] Stopping app process $($_.Id)"
    Stop-Process -Id $_.Id -Force
}

# 2) Stop ONLY the backend python started by THIS installation.
#    Requires both "app.main:app" in the command line and this install path,
#    so unrelated python processes (IDE, other projects, agents) are untouched.
$esc = [regex]::Escape($InstallDir)
$procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue
foreach ($p in $procs) {
    $cl = [string]$p.CommandLine
    if ($cl -and ($cl -match 'app\.main:app') -and ($cl -match $esc)) {
        Write-Host "[KB-Assistant] Stopping backend process $($p.ProcessId)"
        Stop-Process -Id $p.ProcessId -Force
    }
}

# 3) Optionally back up the knowledge base before the installer deletes $INSTDIR.
$dataDir = Join-Path $InstallDir 'backend\data'
if ($KeepData -and (Test-Path -LiteralPath $dataDir)) {
    $backupRoot = $env:KB_BACKUP_ROOT
    if ([string]::IsNullOrEmpty($backupRoot)) {
        $docs = [Environment]::GetFolderPath('MyDocuments')
        $backupRoot = Join-Path $docs 'KB-Assistant-Backup'
    }
    $dest = Join-Path $backupRoot (Get-Date -Format 'yyyyMMdd-HHmmss')
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
    Copy-Item -Path (Join-Path $dataDir '*') -Destination $dest -Recurse -Force -ErrorAction SilentlyContinue
    Set-Content -Path (Join-Path $backupRoot 'LATEST.txt') -Value $dest -Encoding UTF8
    Write-Host "[KB-Assistant] Data backed up to: $dest"
} else {
    Write-Host "[KB-Assistant] Data backup skipped."
}

Write-Host '[KB-Assistant] Cleanup finished.'
