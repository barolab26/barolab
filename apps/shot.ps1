# Emulator helper: optional launch / tap / key, then a screenshot saved under apps\qa\shots\<name>.png (shrunk for review).
# usage: .\shot.ps1 -Name greeting-home [-Launch com.barolab.morningcard.debug] [-Tap "540,1200"] [-Key BACK] [-Wait 3]
param([string]$Name, [string]$Launch, [string]$Tap, [string]$Key, [string]$Swipe, [int]$Wait = 3)
$adb = Join-Path $env:LOCALAPPDATA 'BaroLabAndroid\sdk\platform-tools\adb.exe'
if ($Launch) { & $adb shell monkey -p $Launch -c android.intent.category.LAUNCHER 1 2>$null | Out-Null }
if ($Tap) { $x, $y = $Tap.Split(','); & $adb shell input tap $x $y }
if ($Swipe) { & $adb shell input swipe @($Swipe.Split(',')) }
if ($Key) { & $adb shell input keyevent "KEYCODE_$Key" }
Start-Sleep $Wait
$dir = Join-Path $PSScriptRoot 'qa\shots'
New-Item -ItemType Directory -Force $dir | Out-Null
& $adb shell screencap -p /sdcard/s.png
& $adb pull /sdcard/s.png (Join-Path $dir "$Name-full.png") 2>$null | Out-Null
ffmpeg -y -loglevel error -i (Join-Path $dir "$Name-full.png") -vf "scale=540:-1" (Join-Path $dir "$Name.png")
Remove-Item (Join-Path $dir "$Name-full.png")
"$Name saved; focus: $((& $adb shell dumpsys window 2>$null | Select-String 'mCurrentFocus' | Select-Object -First 1).Line.Trim())"
