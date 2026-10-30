param([ValidateSet('debug','internal','verify','release')][string]$Mode = 'debug', [string]$SdkRoot = $env:ANDROID_HOME)
$ErrorActionPreference = 'Stop'
$toolRoot = Join-Path $env:LOCALAPPDATA 'BaroLabAndroid'
if (!$env:JAVA_HOME) {
    $jdk = Get-ChildItem -LiteralPath (Join-Path $toolRoot 'jdk') -Directory -ErrorAction SilentlyContinue | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'bin\java.exe') } | Select-Object -First 1
    if (!$jdk) { throw 'Set JAVA_HOME to JDK 17 or newer before building.' }
    $env:JAVA_HOME = $jdk.FullName
}
if (!$SdkRoot) { $SdkRoot = Join-Path $toolRoot 'sdk' }
if (!(Test-Path -LiteralPath (Join-Path $SdkRoot 'platforms\android-36\android.jar'))) { throw 'Install Android SDK platform 36 and provide -SdkRoot.' }
if (Test-Path -LiteralPath (Join-Path $toolRoot 'gradle-home')) { $env:GRADLE_USER_HOME = Join-Path $toolRoot 'gradle-home' }
$sdkProperty = $SdkRoot.Replace('\','/').Replace(':','\:')
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'local.properties'), "sdk.dir=$sdkProperty`n", [Text.UTF8Encoding]::new($false))
$tasks = switch ($Mode) {
    'debug' { @('assembleDebug') }
    'internal' { @('testDebugUnitTest','lintDebug','bundleInternal','assembleInternal') }
    'verify' { @('testDebugUnitTest','lintDebug') }
    'release' { @('bundleRelease') }
}
Push-Location $PSScriptRoot
try {
    # Windows PowerShell treats native stderr warnings as errors under Stop.
    # Gradle's exit code, rather than the output stream used, determines success.
    $previousErrorAction = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & (Join-Path $PSScriptRoot 'gradlew.bat') '--project-dir' $PSScriptRoot '--no-daemon' @tasks
        $gradleExitCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousErrorAction }
    if ($gradleExitCode -ne 0) { throw "Android $Mode build failed with exit code $gradleExitCode." }
} finally { Pop-Location }
