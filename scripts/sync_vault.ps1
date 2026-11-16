<#
  Deal Radar -> Obsidian one-way sync (run by the DealRadarSync scheduled task).
  1. git pull --ff-only the repo (public repo: no credentials needed)
  2. robocopy Obsidian-Vault\ -> <VAULT>\Deal-Radar\   (/E only: never /MIR or /PURGE, so nothing is deleted)
  robocopy exit codes 0-7 = success, 8+ = failure.
#>
param(
  [string]$RepoDir = "",
  [string]$Vault = ""
)
$ErrorActionPreference = 'Continue'
$stateDir = Join-Path $env:LOCALAPPDATA 'DealRadar'
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$log = Join-Path $stateDir 'sync.log'
function Log([string]$m) { Add-Content -Path $log -Value ("{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $m) -Encoding UTF8 }

$cfgPath = Join-Path $stateDir 'config.json'
if (Test-Path $cfgPath) {
  $cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if (-not $RepoDir) { $RepoDir = $cfg.repo }
  if (-not $Vault) { $Vault = $cfg.vault }
}
if (-not $RepoDir) { $RepoDir = Join-Path $env:USERPROFILE 'energy-protein-radar' }
if (-not $Vault -or -not (Test-Path $Vault)) { Log "ERROR vault path not set or missing: '$Vault' (re-run scripts\setup_windows.ps1)"; exit 2 }

# Keep the log from growing forever (~1 MB cap)
if ((Test-Path $log) -and ((Get-Item $log).Length -gt 1MB)) { Move-Item $log "$log.old" -Force }

Log "sync start repo=$RepoDir vault=$Vault"
$env:GIT_TERMINAL_PROMPT = '0'
$out = & git -C $RepoDir pull --ff-only 2>&1
$gitRc = $LASTEXITCODE
$out | ForEach-Object { Log "git: $_" }
if ($gitRc -ne 0) { Log "ERROR git pull failed (exit $gitRc)"; exit 1 }

$src = Join-Path $RepoDir 'Obsidian-Vault'
$dst = Join-Path $Vault 'Deal-Radar'
& robocopy $src $dst /E /R:2 /W:5 /NP /NJH /NJS "/LOG+:$log" | Out-Null
$rc = $LASTEXITCODE
if ($rc -ge 8) { Log "ERROR robocopy failed (exit $rc)"; exit $rc }
Log "sync ok (robocopy exit $rc)"
exit 0
