#requires -Version 5.1
<#
.SYNOPSIS
  BaroLab GitHub Local Workspace Bootstrapper (C:\10_Project\BaroLab)
  다른 PC에서 git clone 후 즉시 실행 환경을 구성하고 스케줄러를 로컬 경로(C:\10_Project\BaroLab)로 전환합니다.
#>
[CmdletBinding()]
param(
    [string]$RepoRoot = $PSScriptRoot,
    [switch]$InstallPackages,
    [switch]$SkipTaskScheduler
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'

if (-not $RepoRoot) {
    $RepoRoot = 'C:\10_Project\BaroLab'
}
$RepoRoot = [System.IO.Path]::GetFullPath($RepoRoot).TrimEnd('\')

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host " [BaroLab GitHub 로컬 환경 부트스트랩]" -ForegroundColor Cyan
Write-Host " - 로컬 저장소 경로 : $RepoRoot"
Write-Host "======================================================================" -ForegroundColor Cyan

# 1. Git 표준 설정
if (Test-Path (Join-Path $RepoRoot ".git")) {
    git -C $RepoRoot config user.name "barolab26"
    git -C $RepoRoot config user.email "barolab26@gmail.com"
    git -C $RepoRoot config core.autocrlf false
    git -C $RepoRoot config core.quotepath false
    git -C $RepoRoot config pull.rebase true
    Write-Host "[1/5] Git 설정 완료 (barolab26 / origin main)" -ForegroundColor Green
}

# 2. 필수 런타임 디렉토리 생성 (.gitignore 제외 폴더)
$runtimeDirs = @(
    "cf_posting\data\secure",
    "cf_posting\output",
    "naver_blog_posting\output",
    "server\data\secure",
    "server\data-secret",
    "server\data\chats",
    "server\data\control-jobs",
    "server\data\kin-drafts",
    "server\data\threads-drafts",
    "server\data\radar",
    "data\memories"
)
foreach ($rel in $runtimeDirs) {
    $full = Join-Path $RepoRoot $rel
    if (-not (Test-Path $full)) {
        New-Item -ItemType Directory -Force -Path $full | Out-Null
    }
}
Write-Host "[2/5] 필수 런타임 디렉토리 구조 생성 완료" -ForegroundColor Green

# 3. Python / Pythonw 실행 파일 자동 탐색
$pythonExe = $null
$pythonwExe = $null
$pyCandidates = @(Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)
if ($pyCandidates.Count -gt 0) {
    $pythonExe = $pyCandidates[0].FullName
    $pythonwExe = Join-Path $pyCandidates[0].DirectoryName "pythonw.exe"
} else {
    $cmdPy = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmdPy) {
        $pythonExe = $cmdPy.Source
        $pythonwExe = Join-Path (Split-Path $pythonExe -Parent) "pythonw.exe"
    }
}
if (-not $pythonExe -or -not (Test-Path $pythonExe)) {
    throw "Python 설치 경로를 찾을 수 없습니다. Python 3.11+ 설치 후 다시 실행해 주세요."
}
if (-not (Test-Path $pythonwExe)) {
    $pythonwExe = $pythonExe
}
Write-Host "[3/5] Python 런타임 감지 완료: $pythonExe" -ForegroundColor Green

# 4. 선택적 패키지 설치
if ($InstallPackages) {
    Write-Host "[4/5] 필수 Python 패키지 설치 중..." -ForegroundColor Yellow
    & $pythonExe -m pip install --upgrade requests beautifulsoup4 playwright opencv-python Pillow piexif numpy websocket-client fastapi uvicorn
    & $pythonExe -m playwright install chromium
} else {
    Write-Host "[4/5] 패키지 설치 생략 (설치 필요 시 -InstallPackages 옵션 사용)" -ForegroundColor Gray
}

# 5. 구 NAS 경로(\\otns\yoonlab 또는 Y:\10_Project\BaroLab) 프로세스 정리 및 스케줄러를 로컬(C:\10_Project\BaroLab)로 전환
if (-not $SkipTaskScheduler) {
    $nasProcs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -and (
            $_.CommandLine -match '\\\\otns\\yoonlab\\10_Project\\BaroLab' -or
            $_.CommandLine -match 'Y:[/\\]10_Project[/\\]BaroLab'
        )
    })
    foreach ($np in $nasProcs) {
        try {
            Stop-Process -Id $np.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host "  - 구 NAS 프로세스 종료: PID $($np.ProcessId)" -ForegroundColor Yellow
        } catch {}
    }

    $taskDefs = @(
        @{ Name = "BaroLab-CF-Cleaner";       Args = "-B -X utf8 `"$RepoRoot\server\windows_worker.py`" --task cleaner" },
        @{ Name = "BaroLab-Dashboard-Worker"; Args = "-B -X utf8 `"$RepoRoot\server\windows_worker.py`" --task serve" },
        @{ Name = "BaroLab-Metrics-Collector";Args = "-B -X utf8 `"$RepoRoot\server\windows_worker.py`" --task metrics" },
        @{ Name = "BaroLab-Naver-Daily";      Args = "-B -X utf8 `"$RepoRoot\server\windows_worker.py`" --task naver-daily" },
        @{ Name = "BaroLab-Naver-Monitor";    Args = "-B -X utf8 `"$RepoRoot\server\windows_worker.py`" --task naver-monitor" },
        @{ Name = "BaroLab-System-Watchdog";  Args = "-B -X utf8 `"$RepoRoot\common\system_watchdog.py`" --run --source task-scheduler" },
        @{ Name = "BaroLab-Kin-Seven-Day-Pilot";             Args = "-u -B -X utf8 `"$RepoRoot\naver_kin\scheduler.py`" --tick --scheduled" },
        @{ Name = "BaroLab-Kin-Seven-Day-Pilot-Measurement"; Args = "-u -B -X utf8 `"$RepoRoot\naver_kin\scheduler.py`" --measure --scheduled" },
        @{ Name = "BaroLab-Threads-Pilot";    Args = "-m threads_posting.scheduler --tick" },
        @{ Name = "BaroLab-Memory-Service";   Args = "-B -X utf8 `"$RepoRoot\server\memory_service.py`" --port 8792" }
    )

    foreach ($td in $taskDefs) {
        $existing = Get-ScheduledTask -TaskName $td.Name -ErrorAction SilentlyContinue
        if ($existing) {
            $action = New-ScheduledTaskAction -Execute $pythonwExe -Argument $td.Args -WorkingDirectory $RepoRoot
            Set-ScheduledTask -TaskName $td.Name -Action $action | Out-Null
            Enable-ScheduledTask -TaskName $td.Name | Out-Null
            Write-Host "  - 스케줄러 로컬 경로 전환 완료: $($td.Name) -> $RepoRoot" -ForegroundColor Green
        } else {
            try {
                $action = New-ScheduledTaskAction -Execute $pythonwExe -Argument $td.Args -WorkingDirectory $RepoRoot
                $trigger = New-ScheduledTaskTrigger -AtLogOn
                Register-ScheduledTask -TaskName $td.Name -Action $action -Trigger $trigger -Description "BaroLab $($td.Name)" -ErrorAction SilentlyContinue | Out-Null
                Write-Host "  - 신규 스케줄러 등록 완료: $($td.Name)" -ForegroundColor Green
            } catch {}
        }
    }

    foreach ($startName in @("BaroLab-Dashboard-Worker", "BaroLab-CF-Cleaner", "BaroLab-Memory-Service")) {
        $st = Get-ScheduledTask -TaskName $startName -ErrorAction SilentlyContinue
        if ($st) {
            Start-ScheduledTask -TaskName $startName -ErrorAction SilentlyContinue
        }
    }
    Write-Host "[5/5] Windows 작업 스케줄러 로컬($RepoRoot) 전환 및 재기동 완료" -ForegroundColor Green
}

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host " 완료! 이제 모든 작업은 NAS가 아닌 $RepoRoot (GitHub 연동)에서 실행됩니다." -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Cyan
