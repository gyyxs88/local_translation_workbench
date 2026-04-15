[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CliArgs
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$env:PYTHONUTF8 = "1"

function Resolve-ToolPython {
    $toolRoot = Split-Path -Parent $PSScriptRoot
    $repoRoot = Split-Path -Parent (Split-Path -Parent $toolRoot)
    $candidates = @(
        (Join-Path $repoRoot ".venv\Scripts\python.exe"),
        (Join-Path $toolRoot ".venv\Scripts\python.exe")
    )

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return (Resolve-Path $candidate).ProviderPath
        }
    }

    throw "No available virtual environment Python was found."
}

$pythonExe = Resolve-ToolPython
$toolRoot = Split-Path -Parent $PSScriptRoot

Push-Location $toolRoot
try {
    & $pythonExe -m app.cli @CliArgs
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

exit $exitCode
