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

# 1. Agents + command: plain copy.
New-Item -ItemType Directory -Force (Join-Path $dest 'agents'), (Join-Path $dest 'commands') | Out-Null
Copy-Item (Join-Path $kit 'core\agents\*.md')   (Join-Path $dest 'agents')   -Force
Copy-Item (Join-Path $kit 'core\commands\*.md') (Join-Path $dest 'commands') -Force
"agents:   " + ((Get-ChildItem (Join-Path $kit 'core\agents\*.md')).BaseName -join ', ')
"commands: " + ((Get-ChildItem (Join-Path $kit 'core\commands\*.md')).BaseName -join ', ')

# 2. CLAUDE.md: replace the marker block, append it if absent. Your own rules stay.
$md    = Join-Path $dest 'CLAUDE.md'
$block = "<!-- orchestration-kit (fork of SirRuggie/claude-code-orchestration-kit, source $kit) -->`n" +
         (Get-Content (Join-Path $kit 'core\CLAUDE.md') -Raw) + "<!-- /orchestration-kit -->`n"
$cur   = if (Test-Path $md) { Get-Content $md -Raw } else { '' }
$pat   = '(?s)<!-- orchestration-kit.*?<!-- /orchestration-kit -->\r?\n?'
$new   = if ($cur -match $pat) { [regex]::Replace($cur, $pat, $block.Replace('$', '$$')) }
         else { $cur.TrimEnd() + "`n`n" + $block }
if ($new -ne $cur) { Write-Lf $md $new; "CLAUDE.md: kit block " + ($(if ($cur -match $pat) { 'replaced' } else { 'appended' })) }
else { "CLAUDE.md: unchanged" }

# 3. settings.json: deep-merge core/settings.user.json. Objects merge, lists union, scalars win.
$sf   = Join-Path $dest 'settings.json'
$frag = Get-Content (Join-Path $kit 'core\settings.user.json') -Raw | ConvertFrom-Json -AsHashtable
$set  = if (Test-Path $sf) { Get-Content $sf -Raw | ConvertFrom-Json -AsHashtable } else { [ordered]@{} }
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
    if (Test-Path $sf) { Copy-Item $sf "$sf.bak-kit-$(Get-Date -Format yyyyMMdd-HHmmss)" }
    Write-Lf $sf $json
    "settings.json: merged (backup written)"
} else { "settings.json: unchanged" }

# 4. Guard: the one env var that silently defeats every agent's frontmatter effort.
if ($set['env'] -and $set['env']['CLAUDE_CODE_EFFORT_LEVEL']) {
    Write-Warning "settings.json env.CLAUDE_CODE_EFFORT_LEVEL is set. It overrides every agent's frontmatter effort. Remove it."
}
if ($set['env'] -and $set['env']['CLAUDE_CODE_SUBAGENT_MODEL_FORCE']) {
    Write-Warning "settings.json env.CLAUDE_CODE_SUBAGENT_MODEL_FORCE is set. It ignores every agent's model pin. Remove it."
}

"done. New sessions pick up the agents; /status confirms the settings file loaded; /tasks shows a running subagent's model."
