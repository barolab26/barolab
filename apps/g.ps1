# Runs the installed Gradle (the wrapper jar is not in this checkout) for the daily apps or the bible project.
# usage: .\g.ps1 daily :greeting:assembleDebug ...   |   .\g.ps1 bible :app:assembleDebug ...
param([ValidateSet('daily','bible')][string]$Project, [Parameter(ValueFromRemainingArguments=$true)][string[]]$Tasks)
$tool = Join-Path $env:LOCALAPPDATA 'BaroLabAndroid'
$env:JAVA_HOME = (Get-ChildItem (Join-Path $tool 'jdk') -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'bin/java.exe') } | Select-Object -First 1).FullName
$env:ANDROID_HOME = Join-Path $tool 'sdk'
$env:GRADLE_USER_HOME = Join-Path $tool 'gradle-home'
$dir = if ($Project -eq 'bible') { Join-Path $PSScriptRoot 'bible' } else { $PSScriptRoot }
[IO.File]::WriteAllText((Join-Path $dir 'local.properties'), 'sdk.dir=' + $env:ANDROID_HOME.Replace('\','/').Replace(':','\:') + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
$gradle = (Get-ChildItem (Join-Path $tool 'gradle') -Recurse -Filter gradle.bat | Select-Object -First 1).FullName
$log = Join-Path $env:TEMP "apps-$Project.log"
$p = Start-Process -FilePath $gradle -ArgumentList (@('--project-dir', $dir, '--no-daemon', '--offline') + $Tasks) -WorkingDirectory $dir -NoNewWindow -Wait -PassThru -RedirectStandardOutput $log -RedirectStandardError "$log.err"
Get-Content $log, "$log.err" | Select-String 'error:|warning:|What went wrong|FAILED|BUILD|tests completed|Could not|Exception' | Select-Object -First 40 | ForEach-Object { $_.Line.Substring(0, [Math]::Min(240, $_.Line.Length)) }
"exit $($p.ExitCode)"
exit $p.ExitCode
