param(
  [Parameter(Mandatory = $true)]
  [string]$Repository,

  [Parameter(Mandatory = $true)]
  [string]$Tag,

  [Parameter(Mandatory = $true)]
  [string]$Name,

  [Parameter(Mandatory = $true)]
  [string]$NotesFile,

  [Parameter(Mandatory = $true)]
  [string[]]$Assets
)

$ErrorActionPreference = "Stop"

$token = $env:PUBLIC_RELEASE_TOKEN
if (-not $token) {
  $token = $env:GITHUB_TOKEN
}
if (-not $token) {
  throw "缺少 PUBLIC_RELEASE_TOKEN 或 GITHUB_TOKEN。"
}

$headers = @{
  Authorization = "Bearer $token"
  Accept = "application/vnd.github+json"
  "X-GitHub-Api-Version" = "2022-11-28"
}

$apiBase = "https://api.github.com/repos/$Repository"
$release = $null
try {
  $release = Invoke-RestMethod -Method Get -Uri "$apiBase/releases/tags/$Tag" -Headers $headers
}
catch {
  if ($_.Exception.Response.StatusCode.value__ -ne 404) {
    throw
  }
}

$notes = Get-Content -Raw -Encoding UTF8 -LiteralPath $NotesFile
if (-not $release) {
  $body = @{
    tag_name = $Tag
    target_commitish = "main"
    name = $Name
    body = $notes
    draft = $false
    prerelease = $false
  } | ConvertTo-Json
  $release = Invoke-RestMethod -Method Post -Uri "$apiBase/releases" -Headers $headers -Body $body -ContentType "application/json"
}
else {
  $body = @{
    name = $Name
    body = $notes
    draft = $false
    prerelease = $false
  } | ConvertTo-Json
  $release = Invoke-RestMethod -Method Patch -Uri "$apiBase/releases/$($release.id)" -Headers $headers -Body $body -ContentType "application/json"
}

foreach ($assetPath in $Assets) {
  $resolvedAssetPath = Resolve-Path $assetPath
  $assetName = Split-Path -Leaf $resolvedAssetPath
  $existingAsset = $release.assets | Where-Object { $_.name -eq $assetName } | Select-Object -First 1
  if ($existingAsset) {
    Invoke-RestMethod -Method Delete -Uri $existingAsset.url -Headers $headers | Out-Null
  }

  $contentType = if ($assetName.EndsWith(".zip", [StringComparison]::OrdinalIgnoreCase)) {
    "application/zip"
  }
  else {
    "text/plain"
  }
  $uploadUri = "https://uploads.github.com/repos/$Repository/releases/$($release.id)/assets?name=$([uri]::EscapeDataString($assetName))"
  Invoke-RestMethod -Method Post -Uri $uploadUri -Headers $headers -ContentType $contentType -InFile $resolvedAssetPath | Out-Null
}

$published = Invoke-RestMethod -Method Get -Uri "$apiBase/releases/tags/$Tag" -Headers $headers
[pscustomobject]@{
  url = $published.html_url
  assets = @($published.assets | ForEach-Object { $_.name })
} | ConvertTo-Json -Compress
