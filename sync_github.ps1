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

Write-Host "[GitHub Sync] Pulling latest from origin/main..." -ForegroundColor Cyan
git -C $RepoRoot pull --rebase --autostash origin main

git -C $RepoRoot add -A
$status = git -C $RepoRoot status --porcelain
if ($status) {
    Write-Host "[GitHub Sync] Committing and pushing changes..." -ForegroundColor Cyan
    git -C $RepoRoot commit -m $Message
    git -C $RepoRoot push origin main
    Write-Host "[GitHub Sync] Push complete!" -ForegroundColor Green
} else {
    Write-Host "[GitHub Sync] Working tree is already up to date with origin/main." -ForegroundColor Green
}
