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
"agents:        " + ((Get-ChildItem (Join-Path $kit 'core\agents\*.md')).BaseName -join ', ')
"commands:      " + ((Get-ChildItem (Join-Path $kit 'core\commands\*.md')).BaseName -join ', ')
"skills:        " + ((Get-ChildItem (Join-Path $kit 'core\skills') -Directory).Name -join ', ')
"output-styles: " + ((Get-ChildItem (Join-Path $kit 'core\output-styles\*.md')).BaseName -join ', ')

# 2. CLAUDE.md: replace the marker block, append it if absent. Your own rules stay.
$md    = Join-Path $dest 'CLAUDE.md'
$block = "<!-- orchestration-kit (fork of SirRuggie/claude-code-orchestration-kit, source $kit) -->`n" +
         (Get-Content (Join-Path $kit 'core\CLAUDE.md') -Raw) + "<!-- /orchestration-kit -->`n"
$cur   = if (Test-Path $md) { Get-Content $md -Raw } else { '' }
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
$set  = if (Test-Path $sf) { Get-Content $sf -Raw | ConvertFrom-Json -AsHashtable } else { [ordered]@{} }
# Pre-merge copy of the user's own settings. The guards in step 4 must see what the USER had:
# the merge below lets the fragment's scalars win, so a conflict is invisible afterwards.
$pre  = if (Test-Path $sf) { Get-Content $sf -Raw | ConvertFrom-Json -AsHashtable } else { [ordered]@{} }
function Merge-Into($dst, $src) {
    foreach ($k in $src.Keys) {
        $v = $src[$k]
        if ($v -is [Collections.IDictionary] -and $dst[$k] -is [Collections.IDictionary]) { Merge-Into $dst[$k] $v }
        elseif ($v -is [array] -and $dst[$k] -is [array]) { $dst[$k] = @(@($dst[$k]) + @($v) | Select-Object -Unique) }
        else { $dst[$k] = $v }
    }
}
Merge-Into $set $frag
$json = ($set | ConvertTo-Json -Depth 20) + "`n"
$old  = if (Test-Path $sf) { Get-Content $sf -Raw } else { '' }
if ($json.Replace("`r`n", "`n") -ne $old.Replace("`r`n", "`n")) {
    # Report the backup only when one was actually taken: on a fresh machine there is no
    # settings.json to copy, and claiming a backup that does not exist is how someone
    # edits confidently and finds nothing to roll back to.
    $backed = Test-Path $sf
    if ($backed) { Copy-Item $sf "$sf.bak-kit-$(Get-Date -Format yyyyMMdd-HHmmss)" }
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
    $set = Get-Content $sf -Raw | ConvertFrom-Json -AsHashtable
    if (-not $set['hooks']) { $set['hooks'] = [ordered]@{} }
    if (-not $set['hooks']['PreToolUse']) { $set['hooks']['PreToolUse'] = @() }
    $entries = @($set['hooks']['PreToolUse'])
    $mine = $entries | Where-Object { @($_['hooks']) | Where-Object { "$($_['command'])" -like '*md-guard.py*' } }
    if ($mine) {
        $changed = $false
        foreach ($e in $mine) { $e['matcher'] = 'Read|Bash|PowerShell'; foreach ($h in $e['hooks']) { if ($h['command'] -ne $hookCmd) { $h['command'] = $hookCmd; $changed = $true } } }
        "md-guard: " + $(if ($changed) { 'python path updated' } else { 'already registered' })
    } else {
        $entries += [ordered]@{ matcher = 'Read|Bash|PowerShell'; hooks = @([ordered]@{ type = 'command'; command = $hookCmd; timeout = 5000 }) }
        $set['hooks']['PreToolUse'] = $entries
        "md-guard: registered in settings.json"
    }
    # Step 3's backup predates this rewrite, so take our own - and only when we change
    # something the user could want back. On a fresh machine the file here is the one step 3
    # just wrote, so a backup of it preserves nothing.
    $out  = ($set | ConvertTo-Json -Depth 20) + "`n"
    $prev = Get-Content $sf -Raw
    if ($out.Replace("`r`n", "`n") -ne $prev.Replace("`r`n", "`n")) {
        if ($sfPre) { Copy-Item $sf "$sf.bak-kit-$(Get-Date -Format yyyyMMdd-HHmmss)" }
        Write-Lf $sf $out
    }
    $t = & $py (Join-Path $dest 'hooks\md-guard_test.py') 2>&1 | Select-Object -Last 1
    "md-guard self-check: $t"
}

"done. RESTART Claude Code: agents and output styles are read at startup, so the 'orchestrator'"
"      style (the main session's own rules) only applies to a new session. Then /output-style"
"      confirms it is active, /status confirms the settings file loaded, and /context shows"
"      what the shared CLAUDE.md now costs per spawn."
