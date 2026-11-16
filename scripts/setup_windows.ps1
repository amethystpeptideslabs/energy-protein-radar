<#
  Deal Radar — one-time Windows setup. Safe to re-run.
  Run in PowerShell (no admin needed):
    irm https://raw.githubusercontent.com/amethystpeptideslabs/energy-protein-radar/main/scripts/setup_windows.ps1 | iex

  What it does:
    1. Checks Windows, Python 3.12, Git, GitHub CLI (installs missing ones with winget)
    2. git core.longpaths, PYTHONUTF8=1 (user env var)
    3. Clones the repo to %USERPROFILE%\energy-protein-radar (outside OneDrive)
    4. Creates .venv, installs pinned requirements, runs the tests (incl. the emoji UTF-8 test) and a dry run
    5. Finds your Obsidian vault and saves the path to %LOCALAPPDATA%\DealRadar\config.json
    6. Registers the DealRadarSync scheduled task (8:05 AM daily + at log on), runs it once, checks the result
  It never runs a deal scan locally (the cloud job does that) and never writes outside <VAULT>\Deal-Radar\.
#>
function Install-DealRadar {
  $ErrorActionPreference = 'Continue'
  try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
  $RepoUrl = 'https://github.com/amethystpeptideslabs/energy-protein-radar.git'
  $RepoDir = Join-Path $env:USERPROFILE 'energy-protein-radar'
  $StateDir = Join-Path $env:LOCALAPPDATA 'DealRadar'
  $AppUrl = 'https://amethystpeptideslabs.github.io/energy-protein-radar/'
  $results = [ordered]@{}

  function Step([string]$m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
  function Ok([string]$m) { Write-Host "    OK   $m" -ForegroundColor Green }
  function Warn([string]$m) { Write-Host "    WARN $m" -ForegroundColor Yellow }
  function Bad([string]$m) { Write-Host "    FAIL $m" -ForegroundColor Red }
  function Refresh-Path { $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User') }
  function Has([string]$cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
  function Winget-Install([string]$id) {
    if (-not (Has 'winget')) { Bad "winget not found. Install '$id' manually, then re-run."; return $false }
    & winget install -e --id $id --accept-source-agreements --accept-package-agreements --silent --scope user 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { & winget install -e --id $id --accept-source-agreements --accept-package-agreements --silent 2>&1 | Out-Host }
    Refresh-Path
    return $true
  }

  Step 'Windows version'
  $os = [System.Environment]::OSVersion
  Ok "$($os.VersionString) (build $($os.Version.Build))"

  Step 'Python 3.12+'
  $pyArgs = $null
  if (Has 'py') {
    foreach ($candidate in @('-3.12', '-3.13', '-3')) {
      $v = (& py $candidate -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null)
      if ($LASTEXITCODE -eq 0 -and $v -and ([version]$v -ge [version]'3.11')) { $pyArgs = $candidate; break }
    }
  }
  if (-not $pyArgs) {
    Warn 'Python 3.12 not found (ignoring the Microsoft Store python.exe alias); installing with winget...'
    if (-not (Winget-Install 'Python.Python.3.12')) { return }
    $pyArgs = '-3.12'
    if (-not (Has 'py')) { Bad 'Python installed but the py launcher is not on PATH yet. Open a new PowerShell window and re-run this command.'; return }
  }
  Ok ("Python " + (& py $pyArgs --version 2>&1))

  Step 'Git and GitHub CLI'
  if (-not (Has 'git')) { Warn 'Git not found; installing Git for Windows...'; if (-not (Winget-Install 'Git.Git')) { return } }
  if (-not (Has 'git')) { Bad 'Git installed but not on PATH yet. Open a new PowerShell window and re-run.'; return }
  Ok (& git --version)
  if (-not (Has 'gh')) { Warn 'GitHub CLI not found; installing (optional, not needed for sync)...'; Winget-Install 'GitHub.cli' | Out-Null }
  if (Has 'gh') { Ok ((& gh --version 2>$null) | Select-Object -First 1) } else { Warn 'gh not installed (optional).' }
  & git config --global core.longpaths true
  Ok 'git core.longpaths = true'

  Step 'UTF-8 for Python (emoji tiers)'
  [Environment]::SetEnvironmentVariable('PYTHONUTF8', '1', 'User')
  $env:PYTHONUTF8 = '1'
  Ok 'PYTHONUTF8=1 set for your user account'

  Step "Repo at $RepoDir"
  if ($RepoDir -match 'OneDrive') { Warn 'Repo path is inside OneDrive. That breaks .git; use a folder outside OneDrive.' }
  $env:GIT_TERMINAL_PROMPT = '0'
  if (-not (Test-Path (Join-Path $RepoDir '.git'))) {
    & git clone $RepoUrl $RepoDir 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { Bad 'git clone failed.'; return }
    Ok 'cloned'
  } else {
    & git -C $RepoDir pull --ff-only 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { Bad 'git pull --ff-only failed (local changes?).'; return }
    Ok 'already cloned; pulled latest'
  }
  & git -C $RepoDir config core.hooksPath .githooks
  Ok 'pre-commit secret guard enabled (core.hooksPath=.githooks)'

  Step 'Python venv + pinned requirements'
  $venvPy = Join-Path $RepoDir '.venv\Scripts\python.exe'
  if (-not (Test-Path $venvPy)) { & py $pyArgs -m venv (Join-Path $RepoDir '.venv') }
  & $venvPy -m pip install --upgrade pip --quiet 2>&1 | Out-Null
  & $venvPy -m pip install -r (Join-Path $RepoDir 'requirements.txt') --quiet 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { Bad 'pip install failed.'; return }
  Ok 'requirements installed in .venv'

  Step 'Tests (pricing, tiers, validation, records, emoji UTF-8 round trip)'
  Push-Location $RepoDir
  & $venvPy -m pytest -q 2>&1 | Out-Host
  $results['tests'] = ($LASTEXITCODE -eq 0)
  if ($results['tests']) { Ok 'all tests passed on Windows' } else { Bad 'tests failed (see above)' }
  & $venvPy deal_hunter.py --dry-run 2>&1 | Select-Object -Last 4 | Out-Host
  $results['dry_run'] = ($LASTEXITCODE -eq 0)
  Pop-Location

  Step 'Obsidian vault'
  $vaults = @()
  $reg = Join-Path $env:APPDATA 'obsidian\obsidian.json'
  if (Test-Path $reg) {
    $j = Get-Content $reg -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($p in $j.vaults.PSObject.Properties) { if ($p.Value.path -and (Test-Path $p.Value.path)) { $vaults += $p.Value.path } }
  }
  if ($vaults.Count -eq 0) {
    Warn 'No vaults in Obsidian''s registry; searching for .obsidian folders...'
    $roots = @($env:USERPROFILE, $env:OneDrive, (Join-Path $env:USERPROFILE 'iCloudDrive')) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique
    foreach ($r in $roots) {
      Get-ChildItem $r -Directory -Recurse -Depth 5 -Filter .obsidian -Force -ErrorAction SilentlyContinue |
        ForEach-Object { $vaults += $_.Parent.FullName }
    }
  }
  $vaults = @($vaults | Select-Object -Unique)
  $vault = $null
  $cfgPath = Join-Path $StateDir 'config.json'
  if ($vaults.Count -eq 1) {
    $vault = $vaults[0]
  } else {
    if ($vaults.Count -gt 1) {
      Write-Host '    Found these vaults:'
      for ($i = 0; $i -lt $vaults.Count; $i++) { Write-Host ("      [{0}] {1}" -f ($i + 1), $vaults[$i]) }
      $ans = Read-Host '    Number of the vault for Deal Radar notes (or paste a path)'
      if ($ans -match '^\d+$' -and [int]$ans -ge 1 -and [int]$ans -le $vaults.Count) { $vault = $vaults[[int]$ans - 1] } else { $vault = $ans }
    } else {
      $vault = Read-Host '    No Obsidian vault found. Paste your vault folder path'
    }
  }
  $vault = ([string]$vault).Trim([char[]]@([char]34, [char]32))
  if (-not $vault -or -not (Test-Path $vault)) { Bad "Vault path not found: '$vault'. Re-run once Obsidian has a vault."; return }
  Ok "vault: $vault  ->  notes go to $vault\Deal-Radar"
  $sync = 'plain local folder: notes stay on this PC (they will NOT reach your phone)'
  $plugins = Join-Path $vault '.obsidian\core-plugins.json'
  if ((Test-Path $plugins) -and ((Get-Content $plugins -Raw) -match '"sync"\s*(:\s*true|,|\])')) { $sync = 'Obsidian Sync: notes will follow to your phone' }
  elseif ($vault -match 'iCloudDrive|iCloud~md~obsidian') { $sync = 'iCloud for Windows: notes will follow to your iPhone' }
  elseif ($vault -match 'OneDrive') { $sync = 'OneDrive: notes will follow wherever OneDrive syncs' }
  if ($sync -like 'plain*') { Warn $sync } else { Ok $sync }
  $results['vault_sync'] = $sync
  New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
  ([ordered]@{ repo = $RepoDir; vault = $vault } | ConvertTo-Json) | Set-Content -Path $cfgPath -Encoding UTF8
  Ok "saved $cfgPath"

  Step 'Non-interactive git pull (what the task will do)'
  & git -C $RepoDir pull --ff-only 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { Bad 'non-interactive pull failed'; return }
  Ok 'works without prompting'

  Step 'Scheduled task DealRadarSync'
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $RepoDir 'scripts\install_task.ps1') -RepoDir $RepoDir 2>&1 | Out-Host
  if (-not (Get-ScheduledTask -TaskName 'DealRadarSync' -ErrorAction SilentlyContinue)) { Bad 'task was not registered'; return }
  Start-ScheduledTask -TaskName 'DealRadarSync'
  $deadline = (Get-Date).AddSeconds(90)
  do { Start-Sleep -Seconds 3; $t = Get-ScheduledTask -TaskName 'DealRadarSync' } while ($t.State -eq 'Running' -and (Get-Date) -lt $deadline)
  $info = Get-ScheduledTaskInfo -TaskName 'DealRadarSync'
  $results['task_last_result'] = $info.LastTaskResult
  if ($info.LastTaskResult -eq 0) { Ok "LastTaskResult 0 (last run $($info.LastRunTime))" } else { Bad "LastTaskResult $($info.LastTaskResult). Log: $StateDir\sync.log" }
  $master = Join-Path $vault 'Deal-Radar\00-Master-Deal-Profile.md'
  $results['notes_in_vault'] = (Test-Path $master)
  if ($results['notes_in_vault']) { Ok "notes are in $vault\Deal-Radar" } else { Bad 'notes not found in the vault yet; see the sync log' }
  Get-Content (Join-Path $StateDir 'sync.log') -Tail 5 -ErrorAction SilentlyContinue | Out-Host

  Write-Host "`n=================== Deal Radar setup summary ===================" -ForegroundColor Cyan
  $results.GetEnumerator() | ForEach-Object { Write-Host ("  {0,-18} {1}" -f $_.Key, $_.Value) }
  Write-Host "  app                $AppUrl"
  Write-Host "  sync log           $StateDir\sync.log"
  Write-Host "Copy this summary back to Claude if anything says FAIL." -ForegroundColor Cyan
}
Install-DealRadar
