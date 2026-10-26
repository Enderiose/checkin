# scripts/select_targets.ps1
# Interactive multi-select for the scheduled check-in target.
#
#   UP / DOWN : move the cursor
#   SPACE     : toggle the highlighted entry
#   ENTER     : confirm (at least one entry must be selected)
#
# The menu is drawn on the console. The chosen target list is written to
# -OutFile as a single line, e.g. "trae,workbuddy,web" (stdout is used when
# -OutFile is not given). Non-interactive input falls back to -Default.
#
# Called by install_startup_task.bat. Uses only built-in PowerShell, so it
# adds no dependency.

[CmdletBinding()]
param(
    [string]$OutFile = '',
    [string]$Default = 'all'
)

$ErrorActionPreference = 'Stop'

$items = @(
    [pscustomobject]@{ Key = 'trae';      Label = 'Trae SOLO CN' },
    [pscustomobject]@{ Key = 'workbuddy'; Label = 'WorkBuddy' },
    [pscustomobject]@{ Key = 'web';       Label = 'Web sites (.config)' }
)

function Write-Menu([string]$text) { [Console]::Error.WriteLine($text) }

function Clear-Screen {
    # Console.Clear() throws when stdout is redirected; ignore that.
    try { [Console]::Clear() } catch { }
}

function Get-Result {
    $picked = @()
    for ($i = 0; $i -lt $items.Count; $i++) {
        if ($checked[$i]) { $picked += $items[$i].Key }
    }
    return ($picked -join ',')
}

# Initial selection from -Default ("all" or a comma list of keys).
$checked = @()
for ($i = 0; $i -lt $items.Count; $i++) {
    if ($Default -eq 'all') {
        $checked += $true
    } else {
        $checked += (($Default -split ',') -contains $items[$i].Key)
    }
}
if (-not ($checked -contains $true)) {
    for ($i = 0; $i -lt $checked.Count; $i++) { $checked[$i] = $true }
}

function Show-Menu {
    Clear-Screen
    Write-Menu '============================================================'
    Write-Menu 'Select what the scheduled task should check in'
    Write-Menu '============================================================'
    Write-Menu '  UP/DOWN = move    SPACE = toggle    ENTER = confirm'
    Write-Menu ''
    for ($i = 0; $i -lt $items.Count; $i++) {
        $mark = if ($checked[$i]) { '[x]' } else { '[ ]' }
        $arrow = if ($i -eq $cursor) { '>' } else { ' ' }
        Write-Menu ("  {0} {1} {2}" -f $arrow, $mark, $items[$i].Label)
    }
    Write-Menu ''
    if ($message) { Write-Menu ("  " + $message) }
}

# Non-interactive (piped stdin): cannot read keys, use the default.
if ([Console]::IsInputRedirected) {
    $result = Get-Result
    if ($OutFile) { Set-Content -LiteralPath $OutFile -Value $result -Encoding ASCII }
    else { Write-Output $result }
    exit 0
}

$cursor = 0
$message = ''
Show-Menu

$done = $false
while (-not $done) {
    $key = [Console]::ReadKey($true)
    switch ($key.Key) {
        'UpArrow'   { $cursor = ($cursor - 1 + $items.Count) % $items.Count; $message = '' }
        'DownArrow' { $cursor = ($cursor + 1) % $items.Count; $message = '' }
        'Spacebar'  { $checked[$cursor] = -not $checked[$cursor]; $message = '' }
        'Enter'     {
            if ($checked -contains $true) { $done = $true }
            else { $message = 'Select at least one target (SPACE toggles).' }
        }
        default     { }
    }
    if (-not $done) { Show-Menu }
}

Clear-Screen
$result = Get-Result
if ($OutFile) {
    Set-Content -LiteralPath $OutFile -Value $result -Encoding ASCII
} else {
    Write-Output $result
}
