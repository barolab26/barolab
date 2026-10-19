#requires -Version 5.1
<#
.SYNOPSIS
  BaroLab GitHub 양방향 동기화 스크립트 (Pull --rebase + Commit + Push)
#>
[CmdletBinding()]
param(
    [string]$Message = "chore(sync): sync workspace state ($(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))"
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$RepoRoot = [System.IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')

function Assert-GitExit([string]$Operation) {
    if ($LASTEXITCODE -ne 0) { throw "Git $Operation failed (exit $LASTEXITCODE). Sync is incomplete." }
}

# Ignore rules do not protect files already tracked. Refuse their changed/staged versions.
function Assert-NoIgnoredTrackedChanges {
    $ignoredTracked = @(git -C $RepoRoot ls-files -ci --exclude-standard)
    Assert-GitExit 'ignored tracked-file audit'
    $changed = @(git -C $RepoRoot diff HEAD --name-only --diff-filter=ACMR)
    Assert-GitExit 'changed-file audit'
    $unsafe = @($changed | Where-Object { $ignoredTracked -contains $_ })
    if ($unsafe.Count) { throw "Refusing to stage or commit changed files excluded by .gitignore: $($unsafe -join ', ')" }
}

$syncBranch = git -C $RepoRoot branch --show-current
Assert-GitExit 'branch inspection'
if ($syncBranch -ne 'main') { throw "Sync expects main; current branch is $syncBranch. No pull, commit, or push performed." }
Assert-NoIgnoredTrackedChanges
# Fetch the NAS aggregate before Git staging; this does not configure Google/Synology Drive.
$snapshotEndpoint = if ($env:BAROLAB_SNAPSHOT_URL) { $env:BAROLAB_SNAPSHOT_URL } else { 'http://192.168.45.190:8790/api/live-snapshot' }
$snapshotPath = Join-Path $RepoRoot 'server/data/live_snapshot.json'
try {
    $snapshot = Invoke-RestMethod -Uri $snapshotEndpoint -TimeoutSec 90
    if ($snapshot.schema -ne 'barolab-live-snapshot-v1' -or -not $snapshot.generatedAt) { throw 'Invalid live snapshot response' }
    $snapshotAge = [DateTimeOffset]::UtcNow - [DateTimeOffset]::Parse($snapshot.generatedAt)
    if ($snapshotAge.TotalSeconds -lt 0 -or $snapshotAge.TotalSeconds -gt 600) { throw 'NAS snapshot is stale' }
    $snapshotTemp = "$snapshotPath.$PID.tmp"
    [System.IO.File]::WriteAllText($snapshotTemp, ($snapshot | ConvertTo-Json -Depth 30), (New-Object System.Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $snapshotTemp -Destination $snapshotPath -Force
    Write-Host "[GitHub Sync] NAS live snapshot updated ($($snapshot.generatedAt))." -ForegroundColor Cyan
} catch {
    Write-Warning "Live snapshot refresh failed; previous snapshot retained: $($_.Exception.Message)"
}

Assert-NoIgnoredTrackedChanges
git -C $RepoRoot add -A
Assert-GitExit 'stage'
$status = @(git -C $RepoRoot diff --cached --name-only)
Assert-GitExit 'staged-file inspection'
if ($status) {
    Write-Host "[GitHub Sync] Committing and pushing changes..." -ForegroundColor Cyan
    git -C $RepoRoot commit -m $Message
    Assert-GitExit 'commit'
} else {
    Write-Host "[GitHub Sync] No new staged changes; checking pending commits." -ForegroundColor Cyan
}
# Commit local changes before pulling: autostash conflicts must never hide source edits.
Write-Host "[GitHub Sync] Rebasing committed changes on origin/main..." -ForegroundColor Cyan
git -C $RepoRoot pull --rebase --no-autostash origin main
Assert-GitExit 'pull/rebase'
git -C $RepoRoot push origin main
Assert-GitExit 'push'
Write-Host "[GitHub Sync] Push complete!" -ForegroundColor Green
