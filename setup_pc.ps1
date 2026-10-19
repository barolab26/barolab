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

# 2-B. 포터블 브라우저 경로(C:\99_포터블브라우저) 및 전용 배치 확인·자동 연결
if (-not (Test-Path "C:\99_포터블브라우저")) {
    if (Test-Path "C:\portable_brawser") {
        cmd /c mklink /J "C:\99_포터블브라우저" "C:\portable_brawser" | Out-Null
        Write-Host "  - C:\99_포터블브라우저 교차점 연결 완료 (from C:\portable_brawser)" -ForegroundColor Cyan
    } elseif (Test-Path "\\otns\yoonlab\99_포터블브라우저") {
        cmd /c mklink /J "C:\99_포터블브라우저" "\\otns\yoonlab\99_포터블브라우저" | Out-Null
        Write-Host "  - C:\99_포터블브라우저 교차점 연결 완료 (from NAS)" -ForegroundColor Cyan
    }
}
if ((Test-Path "C:\99_포터블브라우저\CentBrowserPotable_baro76650") -and -not (Test-Path "C:\99_포터블브라우저\CentBrowserPortable_baro76650")) {
    cmd /c mklink /J "C:\99_포터블브라우저\CentBrowserPortable_baro76650" "C:\99_포터블브라우저\CentBrowserPotable_baro76650" | Out-Null
}

# 2-C. NAS로부터 누락된 시크릿 키 자동 동기화 (접근 가능한 경우)
$nasSecureCf = "\\otns\yoonlab\10_Project\BaroLab\cf_posting\data\secure"
$localSecureCf = Join-Path $RepoRoot "cf_posting\data\secure"
if ((Test-Path $nasSecureCf) -and -not (Test-Path (Join-Path $localSecureCf "cf_blog_keys.json"))) {
    Copy-Item "$nasSecureCf\*" $localSecureCf -Force -ErrorAction SilentlyContinue
    Write-Host "  - NAS 시크릿 키(cf_blog_keys.json) 로컬 복사 완료" -ForegroundColor Cyan
}

# 2-D. Codex CLI 로컬 설정(~/.barolab/codex-worker.json) 자동 구성
$barolabDir = Join-Path $env:USERPROFILE ".barolab"
if (-not (Test-Path $barolabDir)) { New-Item -ItemType Directory -Force -Path $barolabDir | Out-Null }
$codexWorkerJson = Join-Path $barolabDir "codex-worker.json"
if (-not (Test-Path $codexWorkerJson)) {
    $codexExe = Get-ChildItem "$env:LOCALAPPDATA\OpenAI\Codex\bin\*\codex.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName -First 1
    $codexHome = Join-Path $env:USERPROFILE ".codex"
    if ($codexExe -and (Test-Path $codexHome)) {
        @{ home = $codexHome; executable = $codexExe } | ConvertTo-Json | Set-Content $codexWorkerJson -Encoding UTF8
        Write-Host "  - Codex 작업 호스트 설정 생성 완료: $codexWorkerJson" -ForegroundColor Cyan
    }
}

Write-Host "[2/5] 필수 런타임 디렉토리 및 브라우저/키 설정 완료" -ForegroundColor Green

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

    # 5-B. 관리자 권한 없는 일반 사용자 환경에서도 재부팅 후 자동 기동되도록 Windows 시작프로그램(Startup) 스크립트 항상 등록
    $startupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
    if (Test-Path $startupDir) {
        $cfSchedulerCmd = Join-Path $startupDir "BaroLab-CF-Scheduler-Boot.cmd"
        $cfContent = "@echo off`r`nstart `"`" `"$pythonwExe`" -B -X utf8 `"$RepoRoot\cf_posting\pipeline_runner.py`" --scheduler`r`n"
        Set-Content -Path $cfSchedulerCmd -Value $cfContent -Encoding ASCII
        
        $watchdogCmd = Join-Path $startupDir "BaroLab-System-Watchdog-Boot.cmd"
        $wdContent = "@echo off`r`nstart `"`" `"$pythonwExe`" -B -X utf8 `"$RepoRoot\common\system_watchdog.py`" --run --source logon-startup`r`n"
        Set-Content -Path $watchdogCmd -Value $wdContent -Encoding ASCII
        Write-Host "  - Windows 사용자 시작프로그램(Startup) 자동 기동 스크립트 등록 완료" -ForegroundColor Green
    }

    Write-Host "[5/5] Windows 작업 스케줄러/시작프로그램 로컬($RepoRoot) 전환 및 등록 완료" -ForegroundColor Green
}

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host " 완료! 이제 모든 작업은 NAS가 아닌 $RepoRoot (GitHub 연동)에서 실행됩니다." -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Cyan
