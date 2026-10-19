param([ValidateSet('greeting','magnifier','shopping','bible','all')][string]$App='all',[ValidateSet('debug','internal','verify','release')][string]$Mode='internal')
$ErrorActionPreference='Stop'
if($App -eq 'bible') { & (Join-Path $PSScriptRoot 'bible/build.ps1') -Mode $Mode; return }
$toolRoot=Join-Path $env:LOCALAPPDATA 'BaroLabAndroid'
if(!$env:JAVA_HOME) { $env:JAVA_HOME=(Get-ChildItem (Join-Path $toolRoot 'jdk') -Directory | Where-Object {Test-Path (Join-Path $_.FullName 'bin/java.exe')} | Select-Object -First 1).FullName }
$env:ANDROID_HOME=Join-Path $toolRoot 'sdk'
$env:GRADLE_USER_HOME=Join-Path $toolRoot 'gradle-home'
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'local.properties'),'sdk.dir='+$env:ANDROID_HOME.Replace('\','/').Replace(':','\:')+[Environment]::NewLine,[Text.UTF8Encoding]::new($false))
$modules=if($App -eq 'all') {@('greeting','magnifier','shopping')} else {@($App)}
$tasks=@()
foreach($module in $modules) { $names=switch($Mode) { 'debug' {@('assembleDebug')} 'verify' {@('testDebugUnitTest','lintDebug')} 'internal' {@('testDebugUnitTest','lintDebug','bundleInternal','assembleInternal')} 'release' {@('bundleRelease')} }; foreach($name in $names) {$tasks+=(':'+ $module +':'+$name)} }
Push-Location $PSScriptRoot
try { $previousErrorAction=$ErrorActionPreference; try { $ErrorActionPreference='Continue'; & (Join-Path $PSScriptRoot 'gradlew.bat') '--project-dir' $PSScriptRoot '--no-daemon' @tasks; $code=$LASTEXITCODE } finally {$ErrorActionPreference=$previousErrorAction}; if($code -ne 0) {throw "Daily apps $Mode build failed: $code"} } finally {Pop-Location}

# Bible remains an independent Gradle project; run only after the daily build succeeds.
if($App -eq 'all') { & (Join-Path $PSScriptRoot 'bible/build.ps1') -Mode $Mode }
