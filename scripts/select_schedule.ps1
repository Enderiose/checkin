# scripts/select_schedule.ps1
# Choose when the scheduled check-in runs.
#
#   -Mode auto    interactive: [1] at logon  [2] every day at a specific time
#   -Mode logon   force "at logon"
#   -Mode daily   every day; asks for the time unless -Time is given
#   -Time <raw>   a time to normalise: 08:30, 20:15, 9:30AM, 8:30 PM, 2130
#
# The result is written to -OutFile (or stdout) as a single line:
#     logon
#     daily 21:30          (always normalised to 24h HH:MM)
#
# Non-interactive input falls back to "logon" so unattended installs keep the
# previous behaviour.

[CmdletBinding()]
param(
    [ValidateSet('auto', 'logon', 'daily')]
    [string]$Mode = 'auto',
    [string]$Time = '',
    [string]$OutFile = ''
)

$ErrorActionPreference = 'Stop'

function Write-Menu([string]$text) { [Console]::Error.WriteLine($text) }

function Emit([string]$text) {
    if ($OutFile) { Set-Content -LiteralPath $OutFile -Value $text -Encoding ASCII }
    else { Write-Output $text }
}

function Parse-Time([string]$raw) {
    # Returns a normalised "HH:MM" (24h) or $null when the input is invalid.
    if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
    $t = ($raw.Trim().ToUpperInvariant()) -replace '\s+', ''
    $ampm = $null
    if ($t -match '(AM|PM)$') {
        $ampm = $Matches[1]
        $t = $t.Substring(0, $t.Length - 2)
    }
    $h = $null
    $m = $null
    if ($t -match '^(\d{1,2}):(\d{1,2})$') {
        $h = [int]$Matches[1]
        $m = [int]$Matches[2]
    } elseif ($t -match '^(\d{3,4})$') {
        if ($t.Length -eq 3) { $h = [int]$t.Substring(0, 1); $m = [int]$t.Substring(1, 2) }
        else { $h = [int]$t.Substring(0, 2); $m = [int]$t.Substring(2, 2) }
    } else {
        return $null
    }
    if ($null -eq $h -or $null -eq $m) { return $null }
    if ($ampm) {
        if ($h -lt 1 -or $h -gt 12) { return $null }
        if ($ampm -eq 'AM') { if ($h -eq 12) { $h = 0 } }
        else { if ($h -ne 12) { $h += 12 } }
    }
    if ($h -lt 0 -or $h -gt 23 -or $m -lt 0 -or $m -gt 59) { return $null }
    return ('{0:D2}:{1:D2}' -f $h, $m)
}

# --- explicit choices -------------------------------------------------
if ($Mode -eq 'logon') { Emit 'logon'; exit 0 }

if ($Mode -eq 'daily' -and $Time) {
    $normalised = Parse-Time $Time
    if (-not $normalised) {
        Write-Menu "Invalid time: '$Time' (use HH:MM, H:MM AM/PM, or HHMM)"
        exit 2
    }
    Emit "daily $normalised"
    exit 0
}

# --- no console: keep the old behaviour --------------------------------
if ([Console]::IsInputRedirected) { Emit 'logon'; exit 0 }

# --- interactive -------------------------------------------------------
if ($Mode -eq 'auto') {
    Write-Menu '============================================================'
    Write-Menu 'When should the check-in run?'
    Write-Menu '============================================================'
    Write-Menu '  [1] After logon (current behaviour, with a short delay)'
    Write-Menu '  [2] Every day at a specific time'
    $answer = Read-Host 'Choice [1/2] (default 1)'
    if ($answer -ne '2') { Emit 'logon'; exit 0 }
}

while ($true) {
    Write-Menu ''
    Write-Menu 'Enter the daily time. Examples: 08:30, 20:15, 9:30AM, 8:30 PM, 2130'
    $raw = Read-Host 'Time'
    $normalised = Parse-Time $raw
    if ($normalised) {
        Emit "daily $normalised"
        exit 0
    }
    Write-Menu "  '$raw' is not a valid time - try again (24h HH:MM or 12h H:MM AM/PM)."
}
