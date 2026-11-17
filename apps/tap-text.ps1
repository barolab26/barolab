# Emulator helper: taps the first on-screen element whose text contains -Text (found through a UI dump).
param([string]$Text, [int]$Wait = 2)
$adb = Join-Path $env:LOCALAPPDATA 'BaroLabAndroid\sdk\platform-tools\adb.exe'
$xml = (& $adb shell "uiautomator dump /sdcard/u.xml >/dev/null; cat /sdcard/u.xml" 2>$null) -join ''
$m = [regex]::Match($xml, 'text="[^"]*' + [regex]::Escape($Text) + '[^"]*"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
if (-not $m.Success) { "not found: $Text"; exit 1 }
$x = ([int]$m.Groups[1].Value + [int]$m.Groups[3].Value) / 2; $y = ([int]$m.Groups[2].Value + [int]$m.Groups[4].Value) / 2
& $adb shell input tap $x $y
Start-Sleep $Wait
"tapped '$Text' at $x,$y"
