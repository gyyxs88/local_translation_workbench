param(
  [string]$Version = "",
  [string]$OutputDir = "dist",
  [switch]$NoTimestamp
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot
try {
  if (-not $Version) {
    $versionLine = Select-String -Path "pyproject.toml" -Pattern '^version = "([^"]+)"'
    if (-not $versionLine) {
      throw "pyproject.toml 中未找到 project.version。"
    }
    $Version = $versionLine.Matches[0].Groups[1].Value
  }

  $outputPath = Join-Path $repoRoot $OutputDir
  New-Item -ItemType Directory -Force -Path $outputPath | Out-Null

  $suffix = if ($NoTimestamp) { "" } else { "-" + (Get-Date -Format "yyyyMMdd-HHmmss") }
  $rootName = "local_translation_workbench-$Version$suffix"
  $stageRoot = Join-Path $outputPath "_stage"
  $stagePath = Join-Path $stageRoot $rootName
  $zipPath = Join-Path $outputPath "$rootName.zip"
  $shaPath = "$zipPath.sha256"

  if ((Test-Path -LiteralPath $stagePath) -or (Test-Path -LiteralPath $zipPath) -or (Test-Path -LiteralPath $shaPath)) {
    throw "发布输出已存在：$rootName。请换一个输出目录或清理旧产物。"
  }

  New-Item -ItemType Directory -Path $stagePath | Out-Null

  $excludedPrefixes = @(
    "docs/superpowers/",
    "docs/reports/",
    "data/projects/",
    "novels/",
    "temp/"
  )

  $files = git ls-files | Where-Object {
    $path = $_ -replace "\\", "/"
    foreach ($prefix in $excludedPrefixes) {
      if ($path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        return $false
      }
    }
    return $true
  }

  foreach ($file in $files) {
    $destination = Join-Path $stagePath $file
    $parent = Split-Path -Parent $destination
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    Copy-Item -LiteralPath $file -Destination $destination
  }

  Compress-Archive -Path $stagePath -DestinationPath $zipPath -Force
  $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath
  $hashLine = $hash.Hash.ToLowerInvariant() + "  " + (Split-Path -Leaf $zipPath)
  Set-Content -Encoding ASCII -LiteralPath $shaPath -Value $hashLine

  [pscustomobject]@{
    version = $Version
    root = $rootName
    zip = $zipPath
    sha256 = $shaPath
    file_count = ($files | Measure-Object).Count
  } | ConvertTo-Json -Compress
}
finally {
  Pop-Location
}
