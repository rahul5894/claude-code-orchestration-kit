#Requires -Version 7
# Removes this kit from ~/.claude: the reverse of install.ps1, step for step. Your own files and
# settings stay. `pwsh -File uninstall.ps1 -WhatIf` prints every change and writes nothing.
# Projects are not touched: run /kit-uninstall inside a project for its own kit files.
[CmdletBinding(SupportsShouldProcess)]
param()
$ErrorActionPreference = 'Stop'
$kit  = $PSScriptRoot
$dest = Join-Path $env:USERPROFILE '.claude'
$utf8 = [Text.UTF8Encoding]::new($false)

function Read-Text([string]$path) {
    if (-not (Test-Path $path)) { return '' }
    $t = Get-Content $path -Raw
    if ($null -eq $t) { '' } else { $t }
}
function Write-Lf([string]$path, [string]$text) {
    if ($PSCmdlet.ShouldProcess($path, 'write')) { [IO.File]::WriteAllText($path, $text.Replace("`r`n", "`n"), $utf8) }
}
function Backup([string]$path) {
    if (Test-Path $path) { Copy-Item $path "$path.bak-kit-uninstall-$(Get-Date -Format yyyyMMdd-HHmmss-fff)" }
}
# Says "removed" only when it did: under -WhatIf, ShouldProcess prints the "What if" line instead.
function Drop([string]$path, [string]$label) {
    if ((Test-Path $path) -and $PSCmdlet.ShouldProcess($path, 'remove')) { Remove-Item $path -Recurse -Force; "removed: $label" }
}

# 0. Parse settings.json BEFORE anything is removed. If it cannot be read, the kit's hook
#    entries cannot be taken out of it, and deleting the scripts would leave every tool call
#    running a hook that points at nothing. So stop with nothing changed.
$sf  = Join-Path $dest 'settings.json'
$raw = Read-Text $sf
try { $set = if ($raw.Trim()) { $raw | ConvertFrom-Json -AsHashtable } else { $null } }
catch { throw "settings.json is not valid JSON ($sf). Fix or move it, then re-run. Nothing was changed." }
$frag = Get-Content (Join-Path $kit 'core\settings.user.json') -Raw | ConvertFrom-Json -AsHashtable
$hookFiles = (Get-ChildItem (Join-Path $kit 'core\hooks\*.py')).Name
$styles    = (Get-ChildItem (Join-Path $kit 'core\output-styles\*.md')).BaseName

# 1. settings.json. Hook entries go when their command runs a kit script. A key from
#    core/settings.user.json goes only while its value is still the kit's: a value you changed
#    after installing is yours. outputStyle also goes when it names any kit style, because the
#    style file is deleted below.
#    Your settings from BEFORE the kit decide the rest: install.ps1 backs settings.json up before
#    its first merge, and that copy is the oldest backup, holding none of the kit's hooks (a later
#    one already has them). What it held is yours - an ask/deny rule equal to one of the kit's
#    stays, an effort level the kit overwrote comes back (refuter-02). No such copy = you had no
#    settings before the kit, or the copy is gone: the kit's values simply go.
function Test-KitCommand($h) {
    $c = "$($h['command'])".Replace('\', '/')
    # the same exact test as install.ps1's Test-Runs: the command ENDS in .claude/hooks/<file>
    $hookFiles | Where-Object { $c -match ('/\.claude/hooks/' + [regex]::Escape($_) + '["'']?\s*$') }
}
function Test-HasKitHook($s) {
    if ($s -isnot [Collections.IDictionary] -or $s['hooks'] -isnot [Collections.IDictionary]) { return $false }
    foreach ($ev in $s['hooks'].Values) {
        foreach ($e in @($ev)) {
            if ($e -is [Collections.IDictionary] -and (@($e['hooks']) | Where-Object { $_ -is [Collections.IDictionary] -and (Test-KitCommand $_) })) { return $true }
        }
    }
    $false
}
$orig = $null; $origName = $null
foreach ($b in Get-ChildItem "$sf.bak-kit-2*" -ErrorAction SilentlyContinue | Sort-Object Name) {
    try { $cand = Read-Text $b.FullName | ConvertFrom-Json -AsHashtable } catch { break }
    if ($cand -is [Collections.IDictionary] -and -not (Test-HasKitHook $cand)) { $orig = $cand; $origName = $b.Name }
    break
}
function Remove-Kit($dst, $src, $org) {
    foreach ($k in @($src.Keys)) {
        if (-not $dst.Contains($k)) { continue }
        $v = $src[$k]; $d = $dst[$k]
        $had = $org -is [Collections.IDictionary] -and $org.Contains($k)
        $o = if ($had) { $org[$k] } else { $null }
        if ($v -is [Collections.IDictionary] -and $d -is [Collections.IDictionary]) {
            Remove-Kit $d $v $o
            if ($d.Count -eq 0) { $dst.Remove($k) }
        } elseif ($v -is [array] -and $d -is [array]) {
            $left = @($d | Where-Object { $_ -cnotin $v -or $_ -cin @($o) })
            if ($left.Count) { $dst[$k] = $left } else { $dst.Remove($k) }
        } elseif ((ConvertTo-Json $d -Compress -Depth 20) -ceq (ConvertTo-Json $v -Compress -Depth 20)) {
            if ($had) { $dst[$k] = $o } else { $dst.Remove($k) }
        }
    }
}
if ($set) {
    if ($set['hooks'] -is [Collections.IDictionary]) {
        foreach ($ev in @($set['hooks'].Keys)) {
            $entries = foreach ($e in @($set['hooks'][$ev])) {
                if ($e -isnot [Collections.IDictionary]) { $e; continue }
                $hs = @(@($e['hooks']) | Where-Object { -not ($_ -is [Collections.IDictionary] -and (Test-KitCommand $_)) })
                if ($hs.Count -eq @($e['hooks']).Count) { $e }        # nothing of ours: untouched
                elseif ($hs.Count) { $e['hooks'] = $hs; $e }
            }
            if (@($entries).Count) { $set['hooks'][$ev] = @($entries) } else { $set['hooks'].Remove($ev) }
        }
        if ($set['hooks'].Count -eq 0) { $set.Remove('hooks') }
    }
    if ($set['outputStyle'] -in $styles) {
        if ($orig -and $orig['outputStyle'] -and $orig['outputStyle'] -notin $styles) { $set['outputStyle'] = $orig['outputStyle'] }
        else { $set.Remove('outputStyle') }
    }
    Remove-Kit $set $frag $orig
    # install.ps1 step 3b turned these plugins off. One that was on before the kit goes back on.
    $pol = Get-Content (Join-Path $kit 'core\plugins.json') -Raw | ConvertFrom-Json -AsHashtable
    $ep  = $set['enabledPlugins']
    $off = @()
    if ($ep -is [Collections.IDictionary]) {
        foreach ($id in $pol['disable'].Keys) {
            if ($ep[$id] -ne $false) { continue }
            if ($orig -and $orig['enabledPlugins'] -is [Collections.IDictionary] -and $orig['enabledPlugins'][$id] -eq $true) { $ep[$id] = $true }
            else { $off += $id }
        }
    }
    $json = ($set | ConvertTo-Json -Depth 20) + "`n"
    if ($json.Replace("`r`n", "`n") -ne $raw.Replace("`r`n", "`n")) {
        Backup $sf; Write-Lf $sf $json; "settings.json: kit hooks and kit values removed (backup written)"
    } else { "settings.json: nothing of the kit's found" }
    if ($origName) { "settings.json: your values from before the kit kept or restored, from $origName" }
    if ($off) { "plugins: left disabled (no backup shows them on before the kit): $($off -join ', ')" }
} else { "settings.json: none" }

# 2. CLAUDE.md: an install older than rules/orchestration-kit.md left the kit's rules here
#    between markers. Take that block out; everything outside it is yours and stays.
$md  = Join-Path $dest 'CLAUDE.md'
$cur = Read-Text $md
$pat = '(?s)\r?\n?\r?\n?<!-- orchestration-kit \(fork of (?:(?!<!-- orchestration-kit).)*?<!-- /orchestration-kit -->\r?\n?\r?\n?'
if ($cur -match $pat) {
    $new = [regex]::Replace($cur, $pat, "`n`n").Trim()
    Backup $md; Write-Lf $md $(if ($new) { "$new`n" } else { '' }); "CLAUDE.md: kit block removed (backup written)"
} else { "CLAUDE.md: no kit block" }

# 3. Files the installer copied, by name from this checkout. Never a folder sweep: your own
#    agents, commands, hooks and skill files live in the same folders.
$files = @(
    (Get-ChildItem (Join-Path $kit 'core\agents\*.md')).Name        | ForEach-Object { "agents\$_" }
    (Get-ChildItem (Join-Path $kit 'core\commands\*.md')).Name      | ForEach-Object { "commands\$_" }
    (Get-ChildItem (Join-Path $kit 'core\output-styles\*.md')).Name | ForEach-Object { "output-styles\$_" }
    $hookFiles | ForEach-Object { "hooks\$_" }
    'rules\orchestration-kit.md'
    'kit')
foreach ($f in $files) { Drop (Join-Path $dest $f) $f }
# Skills are folders install.ps1 copies INTO, so a file you added inside one is yours. The kit's
# files go one by one; a folder only once nothing is left in it (refuter-02).
foreach ($n in (Get-ChildItem (Join-Path $kit 'core\skills') -Directory).Name) {
    $src = Join-Path $kit "core\skills\$n"; $dst = Join-Path $dest "skills\$n"
    if (-not (Test-Path $dst)) { continue }
    foreach ($f in Get-ChildItem $src -Recurse -File) {
        $rel = [IO.Path]::GetRelativePath($src, $f.FullName)
        Drop (Join-Path $dst $rel) "skills\$n\$rel"
    }
    foreach ($d in @(Get-ChildItem $dst -Recurse -Directory | Sort-Object { $_.FullName.Length } -Descending) + @(Get-Item $dst)) {
        if (-not (Get-ChildItem $d.FullName -Force)) { Drop $d.FullName ('skills\' + [IO.Path]::GetRelativePath((Join-Path $dest 'skills'), $d.FullName)) }
    }
}
# Every hook imports kit_off.py, so Python left hooks\__pycache__\kit_off.cpython-3xx.pyc.
# Only the kit's own .pyc files go; the folder only if that leaves it empty.
$pyc = Join-Path $dest 'hooks\__pycache__'
if (Test-Path $pyc) {
    foreach ($h in $hookFiles) {
        Get-ChildItem $pyc -Filter "$([IO.Path]::GetFileNameWithoutExtension($h)).*.pyc" | ForEach-Object {
            Drop $_.FullName "hooks\__pycache__\$($_.Name)" }
    }
    if (-not (Get-ChildItem $pyc -Force)) { Drop $pyc 'hooks\__pycache__' }
}

"done. RESTART Claude Code. Projects keep their own kit files (CLAUDE.md, .claude/scratch/);"
"      /kit-uninstall inside a project removes those - run it BEFORE this, it is a kit command."
