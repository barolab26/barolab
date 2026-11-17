# Checks every unverified recorded verse through the Gemini web chat, eight files per question, for both voices.
# The reviewer chat address is put back afterwards so later review questions continue in the same conversation.
$tool = Join-Path $PSScriptRoot 'check-voice-web.cjs'
$g = Join-Path $env:USERPROFILE '.claude\gemini-collab'
if (-not (Test-Path "$g\chat-url.reviewer.txt")) { Copy-Item "$g\chat-url.txt" "$g\chat-url.reviewer.txt" }
foreach ($who in 'female', 'male') {
    for ($round = 0; $round -lt 12; $round++) {
        $prep = node $tool prep $who 8
        $prep
        if ("$prep" -match 'nothing left') { break }
        $ask = ego-browser nodejs -e "await import('file:///C:/Users/baro7/.claude/gemini-collab/ask.mjs')" 2>&1 | ForEach-Object { "$_" } | Where-Object { $_ -match '^\{"url"|Error' }
        if ("$ask" -notmatch '^\{"url"') { "ask failed: $("$ask".Substring(0, [Math]::Min(160, "$ask".Length)))"; break }
        node $tool grade | Where-Object { $_ -match '^BAD|^graded|unusable' }
    }
}
Copy-Item "$g\chat-url.reviewer.txt" "$g\chat-url.txt" -Force
node -e "const v=require('$($PSScriptRoot.Replace('\','/'))/voice-verified.json');console.log('verified female',v.female.length,'male',v.male.length)"
