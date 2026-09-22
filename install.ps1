#Requires -Version 7
# Installs or re-syncs this kit into ~/.claude. Idempotent: run it after every kit change
# and on every new machine. Nothing here replaces a file you own; CLAUDE.md and
# settings.json are merged, agents and commands are copied (the kit is their source of truth).
$ErrorActionPreference = 'Stop'
$kit  = $PSScriptRoot
$dest = Join-Path $env:USERPROFILE '.claude'
$utf8 = [Text.UTF8Encoding]::new($false)

function Write-Lf([string]$path, [string]$text) {
    [IO.File]::WriteAllText($path, $text.Replace("`r`n", "`n"), $utf8)
}

# `Get-Content -Raw` returns $null for a 0-byte file, not ''. Under $ErrorActionPreference =
# 'Stop' the next .TrimEnd() or .Replace() throws "cannot call a method on a null-valued
# expression" and aborts the install. Verified: a 0-byte CLAUDE.md gave rc=1 before this.
function Read-Text([string]$path) {
    if (-not (Test-Path $path)) { return '' }
    $t = Get-Content $path -Raw
    if ($null -eq $t) { '' } else { $t }
}

# 0. Plugin policy, read BEFORE anything is written: step 3b needs it, and an incomplete
#    checkout used to die at that Get-Content with agents and CLAUDE.md already replaced.
$pj = Join-Path $kit 'core\plugins.json'
if (-not (Test-Path $pj)) {
    throw "core/plugins.json is missing from $kit - the checkout is incomplete; nothing was written to settings.json"
}
$pol = Get-Content $pj -Raw | ConvertFrom-Json -AsHashtable

# 1. Agents, commands, skills, output styles: plain copy. Retired agents are removed by name
#    only — never sweep the folder, you may keep your own agents there.
$RETIRED_AGENTS = @('scout')         # dropped in v2: the Explore shadow does locating
$RETIRED_SKILLS = @()                # skill folders a later version renames or drops
$RETIRED_OUTPUT_STYLES = @()         # output styles a later version renames or drops
New-Item -ItemType Directory -Force (Join-Path $dest 'agents'), (Join-Path $dest 'commands'),
    (Join-Path $dest 'skills'), (Join-Path $dest 'output-styles') | Out-Null
Copy-Item (Join-Path $kit 'core\agents\*.md')        (Join-Path $dest 'agents')        -Force
Copy-Item (Join-Path $kit 'core\commands\*.md')      (Join-Path $dest 'commands')      -Force
Copy-Item (Join-Path $kit 'core\output-styles\*.md') (Join-Path $dest 'output-styles') -Force
Copy-Item (Join-Path $kit 'core\skills\*')           (Join-Path $dest 'skills') -Recurse -Force
foreach ($r in $RETIRED_AGENTS) {
    $p = Join-Path $dest "agents\$r.md"
    if (Test-Path $p) { Remove-Item $p -Force; "agents:   removed retired '$r'" }
}
foreach ($r in $RETIRED_SKILLS) {
    $p = Join-Path $dest "skills\$r"
    if (Test-Path $p) { Remove-Item $p -Recurse -Force; "skills:   removed retired '$r'" }
}
foreach ($r in $RETIRED_OUTPUT_STYLES) {
    $p = Join-Path $dest "output-styles\$r.md"
    if (Test-Path $p) { Remove-Item $p -Force; "output-styles: removed retired '$r'" }
}
# The two things /kit-init needs from ANY repo, so a new project can set itself up without
# this checkout being on the machine: the project CLAUDE.md template, and the project audit.
New-Item -ItemType Directory -Force (Join-Path $dest 'kit') | Out-Null
Copy-Item (Join-Path $kit 'extras\project\CLAUDE.md') (Join-Path $dest 'kit\project-template.md') -Force
Copy-Item (Join-Path $kit 'audit_project.py')         (Join-Path $dest 'kit\audit_project.py')     -Force
Copy-Item (Join-Path $kit 'scan_project.py')          (Join-Path $dest 'kit\scan_project.py')      -Force
"agents:        " + ((Get-ChildItem (Join-Path $kit 'core\agents\*.md')).BaseName -join ', ')
"commands:      " + ((Get-ChildItem (Join-Path $kit 'core\commands\*.md')).BaseName -join ', ')
"skills:        " + ((Get-ChildItem (Join-Path $kit 'core\skills') -Directory).Name -join ', ')
"output-styles: " + ((Get-ChildItem (Join-Path $kit 'core\output-styles\*.md')).BaseName -join ', ')

# 2. CLAUDE.md: replace the marker block, append it if absent. Your own rules stay.
$md    = Join-Path $dest 'CLAUDE.md'
$block = "<!-- orchestration-kit (fork of SirRuggie/claude-code-orchestration-kit, source $kit) -->`n" +
         (Get-Content (Join-Path $kit 'core\CLAUDE.md') -Raw) + "<!-- /orchestration-kit -->`n"
$cur   = Read-Text $md
$pat   = '(?s)<!-- orchestration-kit.*?<!-- /orchestration-kit -->\r?\n?'
$new   = if ($cur -match $pat) { [regex]::Replace($cur, $pat, $block.Replace('$', '$$')) }
         else { $cur.TrimEnd() + "`n`n" + $block }
# Compare LF-normalized: Write-Lf strips CRLF on write, so a raw compare never matches and
# the block is rewritten on every run, hiding whether anything actually changed.
if ($new.Replace("`r`n", "`n") -ne $cur.Replace("`r`n", "`n")) {
    Write-Lf $md $new; "CLAUDE.md: kit block " + ($(if ($cur -match $pat) { 'replaced' } else { 'appended' })) }
else { "CLAUDE.md: unchanged" }

# 3. settings.json: deep-merge core/settings.user.json. Objects merge, lists union, scalars win.
$sf   = Join-Path $dest 'settings.json'
# Did the USER have a settings.json before this run? Both backup decisions below hang on it:
# backing up a file the installer itself just wrote only litters the directory.
$sfPre = Test-Path $sf
$frag = Get-Content (Join-Path $kit 'core\settings.user.json') -Raw | ConvertFrom-Json -AsHashtable
$set  = if ((Read-Text $sf).Trim()) { Read-Text $sf | ConvertFrom-Json -AsHashtable } else { [ordered]@{} }
# Pre-merge copy of the user's own settings. The guards in step 4 must see what the USER had:
# the merge below lets the fragment's scalars win, so a conflict is invisible afterwards.
$pre  = if ((Read-Text $sf).Trim()) { Read-Text $sf | ConvertFrom-Json -AsHashtable } else { [ordered]@{} }
function Merge-Into($dst, $src) {
    foreach ($k in $src.Keys) {
        $v = $src[$k]
        if ($v -is [Collections.IDictionary] -and $dst[$k] -is [Collections.IDictionary]) { Merge-Into $dst[$k] $v }
        elseif ($v -is [array] -and $dst[$k] -is [array]) { $dst[$k] = @(@($dst[$k]) + @($v) | Select-Object -Unique) }
        else { $dst[$k] = $v }
    }
}
Merge-Into $set $frag

# 3b. core/plugins.json `disable`: a plugin whose hooks fire in every session cannot be
# half-disabled - Claude Code has no per-plugin hook switch - so the whole plugin goes off and
# the part worth keeping ships as a kit skill. This runs BEFORE the write below on purpose:
# step 3's own compare-and-backup then covers it, so one run still takes one backup and does
# one write. Only `disable` is applied; `allow` exists for verify_live.py C6 to read.
# `$pol` was read in step 0, before the first write. A hand-edited `enabledPlugins` that is a
# string makes the index assignment below throw and takes the whole install with it, so the
# type is checked rather than assumed: anything but a map is reported and skipped.
if ($set['enabledPlugins'] -is [Collections.IDictionary]) {
    foreach ($id in $pol['disable'].Keys) {
        if ($set['enabledPlugins'].Contains($id) -and $set['enabledPlugins'][$id] -ne $false) {
            $set['enabledPlugins'][$id] = $false
            $why = $pol['disable'][$id]
            "plugins: disabled $id (" + $why.Substring(0, [Math]::Min(60, $why.Length)) + ")"
        }
    }
} elseif ($null -ne $set['enabledPlugins']) {
    Write-Warning "settings.json enabledPlugins is not a map; plugin policy not applied"
}
$json = ($set | ConvertTo-Json -Depth 20) + "`n"
$old  = Read-Text $sf
if ($json.Replace("`r`n", "`n") -ne $old.Replace("`r`n", "`n")) {
    # Report the backup only when one was actually taken: on a fresh machine there is no
    # settings.json to copy, and claiming a backup that does not exist is how someone
    # edits confidently and finds nothing to roll back to.
    $backed = Test-Path $sf
    # Millisecond stamp: steps 3 and 5 both back this file up, often inside the same second.
    # At second resolution step 5 silently overwrote step 3's copy - the ONE copy holding the
    # user's pre-kit settings, which is the only thing either backup exists to preserve.
    if ($backed) { Copy-Item $sf "$sf.bak-kit-$(Get-Date -Format yyyyMMdd-HHmmss-fff)" }
    Write-Lf $sf $json
    "settings.json: " + $(if ($backed) { 'merged (backup written)' } else { 'created' })
} else { "settings.json: unchanged" }

# 4. Guards: settings that silently defeat the roster. Each one fails quietly, not loudly.
if ($set['env'] -and $set['env']['CLAUDE_CODE_EFFORT_LEVEL']) {
    Write-Warning "settings.json env.CLAUDE_CODE_EFFORT_LEVEL is set. It overrides every agent's frontmatter effort. Remove it."
}
if ($set['env'] -and $set['env']['CLAUDE_CODE_SUBAGENT_MODEL_FORCE']) {
    Write-Warning "settings.json env.CLAUDE_CODE_SUBAGENT_MODEL_FORCE is set. It ignores every agent's model pin. Remove it."
}
if ($set['maxEffortLevel']) {
    Write-Warning "settings.json maxEffortLevel = '$($set['maxEffortLevel'])' caps every agent's frontmatter effort with no per-agent error. Remove it unless you meant it."
}
if ($set['modelSettings']) {
    foreach ($m in @($set['modelSettings'].Keys)) {
        if ($set['modelSettings'][$m]['maxEffortLevel']) {
            Write-Warning "settings.json modelSettings.$m.maxEffortLevel caps that model's effort silently. Remove it unless you meant it."
        }
    }
}
# These two read $pre, not $set: the kit just overwrote both, so the merged value always
# agrees with the fragment. What is worth saying is that the overwrite happened.
if ($pre['env'] -and $pre['env']['CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS'] -eq '1') {
    Write-Warning "settings.json had env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS = 1; the kit just set it to 0. While teams are on, any subagent Claude names launches as a full teammate session instead, at roughly 7x the tokens."
}
if ($pre['subagentPromptCacheTtl'] -and $pre['subagentPromptCacheTtl'] -ne '1h') {
    Write-Warning "settings.json had subagentPromptCacheTtl = '$($pre['subagentPromptCacheTtl'])'; the kit just set 1h. Subagents get a 5-minute cache TTL by default even on a subscription."
}

# 5. md-guard hook: copy the script, pin a Python 3.12+ path, register once in settings.json.
#    Big markdown files must go through qmd; this hook denies whole-file Read / uncapped shell reads.
New-Item -ItemType Directory -Force (Join-Path $dest 'hooks') | Out-Null
Copy-Item (Join-Path $kit 'core\hooks\*.py') (Join-Path $dest 'hooks') -Force
# The wildcard copy is silent about a file missing from the clone, and the blocks below then
# register a command pointing at nothing - every Read, session start and finished subagent
# would spawn a python that dies. Fail the install instead.
$missing = @('md-guard.py', 'kit-session-start.py', 'kit-subagent-report.py', 'kit-subagent-start.py') |
    Where-Object { -not (Test-Path (Join-Path $dest "hooks\$_")) }
if ($missing) { throw "Hook script(s) missing from the kit checkout, nothing registered: $($missing -join ', ')" }
$py = $null
foreach ($name in 'python3.13', 'python3.12', 'python', 'python3', 'py') {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    $v = & $cmd.Source -c 'import sys; print(sys.version_info >= (3, 12))' 2>$null
    if ($v -eq 'True') { $py = $cmd.Source.Replace('\', '/'); break }
}
if (-not $py) { Write-Warning "md-guard: no Python 3.12+ on PATH. Install one (winget install Python.Python.3.12) and re-run."; }
else {
    $hookCmd = "$py " + (Join-Path $dest 'hooks\md-guard.py').Replace('\', '/')
    $set = if ((Read-Text $sf).Trim()) { Read-Text $sf | ConvertFrom-Json -AsHashtable } else { [ordered]@{} }
    if (-not $set['hooks']) { $set['hooks'] = [ordered]@{} }
    if (-not $set['hooks']['PreToolUse']) { $set['hooks']['PreToolUse'] = @() }
    $entries = @($set['hooks']['PreToolUse'])
    # `$_ -and` first: a pre-existing entry with no `hooks` key makes @($_['hooks']) a @($null),
    # and indexing $null['command'] throws "Cannot index into a null array" - the whole install
    # dying on one hand-written entry. All four sites below are the same shape.
    $mine = $entries | Where-Object { @($_['hooks']) | Where-Object { $_ -and "$($_['command'])" -like '*md-guard.py*' } }
    if ($mine) {
        $changed = $false
        # timeout is re-asserted like matcher: it is in SECONDS, and an install that
        # predates that fix left 5000 (83 minutes) in the user's settings. Only correcting
        # it on a FRESH install would never reach the machines that already have it.
        foreach ($e in $mine) { $e['matcher'] = 'Read|Bash|PowerShell'; foreach ($h in $e['hooks']) { if ($h['command'] -ne $hookCmd) { $h['command'] = $hookCmd; $changed = $true }; if ($h['timeout'] -ne 5) { $h['timeout'] = 5; $changed = $true } } }
        "md-guard: " + $(if ($changed) { 'python path updated' } else { 'already registered' })
    } else {
        $entries += [ordered]@{ matcher = 'Read|Bash|PowerShell'; hooks = @([ordered]@{ type = 'command'; command = $hookCmd; timeout = 5 }) }
        $set['hooks']['PreToolUse'] = $entries
        "md-guard: registered in settings.json"
    }
    # Step 3's backup predates this rewrite, so take our own - and only when we change
    # something the user could want back. On a fresh machine the file here is the one step 3
    # just wrote, so a backup of it preserves nothing.
    $out  = ($set | ConvertTo-Json -Depth 20) + "`n"
    $prev = Read-Text $sf
    if ($out.Replace("`r`n", "`n") -ne $prev.Replace("`r`n", "`n")) {
        if ($sfPre) { Copy-Item $sf "$sf.bak-kit-$(Get-Date -Format yyyyMMdd-HHmmss-fff)" }
        Write-Lf $sf $out
    }
    $t = & $py (Join-Path $dest 'hooks\md-guard_test.py') 2>&1 | Select-Object -Last 1
    "md-guard self-check: $t"

    # 6. kit-session-start hook: one line of context when the project has no FAST GATE row.
    #    Same registration shape as md-guard, on SessionStart. It never writes a file.
    $startCmd = "$py " + (Join-Path $dest 'hooks\kit-session-start.py').Replace('\', '/')
    $set = if ((Read-Text $sf).Trim()) { Read-Text $sf | ConvertFrom-Json -AsHashtable } else { [ordered]@{} }
    if (-not $set['hooks']) { $set['hooks'] = [ordered]@{} }
    if (-not $set['hooks']['SessionStart']) { $set['hooks']['SessionStart'] = @() }
    $sEntries = @($set['hooks']['SessionStart'])
    $sMine = $sEntries | Where-Object { @($_['hooks']) | Where-Object { $_ -and "$($_['command'])" -like '*kit-session-start.py*' } }
    if ($sMine) {
        $changed = $false
        foreach ($e in $sMine) { $e['matcher'] = 'startup|resume|clear|compact'; foreach ($h in $e['hooks']) { if ($h['command'] -ne $startCmd) { $h['command'] = $startCmd; $changed = $true }; if ($h['timeout'] -ne 5) { $h['timeout'] = 5; $changed = $true } } }
        "kit-session-start: " + $(if ($changed) { 'python path updated' } else { 'already registered' })
    } else {
        $sEntries += [ordered]@{ matcher = 'startup|resume|clear|compact'; hooks = @([ordered]@{ type = 'command'; command = $startCmd; timeout = 5 }) }
        $set['hooks']['SessionStart'] = $sEntries
        "kit-session-start: registered in settings.json"
    }
    $out  = ($set | ConvertTo-Json -Depth 20) + "`n"
    $prev = Read-Text $sf
    if ($out.Replace("`r`n", "`n") -ne $prev.Replace("`r`n", "`n")) {
        if ($sfPre) { Copy-Item $sf "$sf.bak-kit-$(Get-Date -Format yyyyMMdd-HHmmss-fff)" }
        Write-Lf $sf $out
    }
    $t2 = & $py (Join-Path $dest 'hooks\kit-session-start_test.py') 2>&1 | Select-Object -Last 1
    "kit-session-start self-check: $t2"

    # 7. kit-subagent-report hook: file every finished subagent's final message into the
    #    project's .claude/scratch/_inbox/, so a report is never lost to a forgotten write.
    $repCmd = "$py " + (Join-Path $dest 'hooks\kit-subagent-report.py').Replace('\', '/')
    $set = if ((Read-Text $sf).Trim()) { Read-Text $sf | ConvertFrom-Json -AsHashtable } else { [ordered]@{} }
    if (-not $set['hooks']) { $set['hooks'] = [ordered]@{} }
    if (-not $set['hooks']['SubagentStop']) { $set['hooks']['SubagentStop'] = @() }
    $rEntries = @($set['hooks']['SubagentStop'])
    $rMine = $rEntries | Where-Object { @($_['hooks']) | Where-Object { $_ -and "$($_['command'])" -like '*kit-subagent-report.py*' } }
    if ($rMine) {
        $changed = $false
        foreach ($e in $rMine) { $e['matcher'] = '*'; foreach ($h in $e['hooks']) { if ($h['command'] -ne $repCmd) { $h['command'] = $repCmd; $changed = $true }; if ($h['timeout'] -ne 5) { $h['timeout'] = 5; $changed = $true } } }
        "kit-subagent-report: " + $(if ($changed) { 'python path updated' } else { 'already registered' })
    } else {
        # '*' = activates on every occurrence of the event, whatever the agent type
        $rEntries += [ordered]@{ matcher = '*'; hooks = @([ordered]@{ type = 'command'; command = $repCmd; timeout = 5 }) }
        $set['hooks']['SubagentStop'] = $rEntries
        "kit-subagent-report: registered in settings.json"
    }
    $out  = ($set | ConvertTo-Json -Depth 20) + "`n"
    $prev = Read-Text $sf
    if ($out.Replace("`r`n", "`n") -ne $prev.Replace("`r`n", "`n")) {
        if ($sfPre) { Copy-Item $sf "$sf.bak-kit-$(Get-Date -Format yyyyMMdd-HHmmss-fff)" }
        Write-Lf $sf $out
    }
    $t3 = & $py (Join-Path $dest 'hooks\kit-subagent-report_test.py') 2>&1 | Select-Object -Last 1
    "kit-subagent-report self-check: $t3"

    # 8. kit-subagent-start hook: inject the DECISIONS.md of every OPEN bucket into a spawned
    #    agent, so a settled decision binds an agent that never saw the conversation.
    $ssCmd = "$py " + (Join-Path $dest 'hooks\kit-subagent-start.py').Replace('\', '/')
    $set = if ((Read-Text $sf).Trim()) { Read-Text $sf | ConvertFrom-Json -AsHashtable } else { [ordered]@{} }
    if (-not $set['hooks']) { $set['hooks'] = [ordered]@{} }
    if (-not $set['hooks']['SubagentStart']) { $set['hooks']['SubagentStart'] = @() }
    $ssEntries = @($set['hooks']['SubagentStart'])
    $ssMine = $ssEntries | Where-Object { @($_['hooks']) | Where-Object { $_ -and "$($_['command'])" -like '*kit-subagent-start.py*' } }
    if ($ssMine) {
        $changed = $false
        foreach ($e in $ssMine) { $e['matcher'] = 'builder|refuter|verifier|debugger|researcher'; foreach ($h in $e['hooks']) { if ($h['command'] -ne $ssCmd) { $h['command'] = $ssCmd; $changed = $true }; if ($h['timeout'] -ne 5) { $h['timeout'] = 5; $changed = $true } } }
        "kit-subagent-start: " + $(if ($changed) { 'python path updated' } else { 'already registered' })
    } else {
        # The five briefed agents only: Explore runs omitClaudeMd and stays tiny on purpose
        $ssEntries += [ordered]@{ matcher = 'builder|refuter|verifier|debugger|researcher'; hooks = @([ordered]@{ type = 'command'; command = $ssCmd; timeout = 5 }) }
        $set['hooks']['SubagentStart'] = $ssEntries
        "kit-subagent-start: registered in settings.json"
    }
    $out  = ($set | ConvertTo-Json -Depth 20) + "`n"
    $prev = Read-Text $sf
    if ($out.Replace("`r`n", "`n") -ne $prev.Replace("`r`n", "`n")) {
        if ($sfPre) { Copy-Item $sf "$sf.bak-kit-$(Get-Date -Format yyyyMMdd-HHmmss-fff)" }
        Write-Lf $sf $out
    }
    $t4 = & $py (Join-Path $dest 'hooks\kit-subagent-start_test.py') 2>&1 | Select-Object -Last 1
    "kit-subagent-start self-check: $t4"
    # From the checkout, not $dest: the fixtures it builds read extras\project\CLAUDE.md
    # beside it, and the published copy in kit\ has no extras\ next to it.
    $t5 = & $py (Join-Path $kit 'scan_project_test.py') 2>&1 | Select-Object -Last 1
    if ($LASTEXITCODE -ne 0) { "scan-project self-check: FAILED (exit $LASTEXITCODE) - see above" }
    else { "scan-project self-check: $t5" }
}

"done. RESTART Claude Code: agents and output styles are read at startup, so the 'orchestrator'"
"      style (the main session's own rules) only applies to a new session. Then /output-style"
"      confirms it is active, /status confirms the settings file loaded, and /context shows"
"      what the shared CLAUDE.md now costs per spawn."
