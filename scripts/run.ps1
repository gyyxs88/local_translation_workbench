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
    $currentRoot = Get-Item $toolRoot

    while ($null -ne $currentRoot) {
        $candidate = Join-Path $currentRoot.FullName ".venv\Scripts\python.exe"
        if (Test-Path $candidate) {
            return (Resolve-Path $candidate).ProviderPath
        }
        $currentRoot = $currentRoot.Parent
    }

    $pathPython = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $pathPython) {
        return $pathPython.Source
    }

    throw "No available Python was found."
}

$pythonExe = Resolve-ToolPython
$toolRoot = Split-Path -Parent $PSScriptRoot

Push-Location $toolRoot
try {
    & $pythonExe -m local_translation_workbench @CliArgs
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

exit $exitCode
