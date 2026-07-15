[CmdletBinding()] param(
  [string]$BundlePath,
  [string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if (-not $BundlePath) { $BundlePath = Join-Path $Root 'dist\mo2-mod-installer-bundle' }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $Root 'release' }
$BundlePath = (Resolve-Path -LiteralPath $BundlePath).Path
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$Manifest = Get-Content -LiteralPath (Join-Path $Root 'skills\mo2-mod-installer\runtime-manifest.json') -Encoding UTF8 -Raw | ConvertFrom-Json
$Version = [string]$Manifest.tool_version
$AssetName = [string]$Manifest.asset_name
$ChecksumName = [string]$Manifest.checksum_asset_name
$Stage = Join-Path ([IO.Path]::GetTempPath()) ('mo2-release-stage-' + [guid]::NewGuid().ToString('N'))
try {
  $StageSkill = Join-Path $Stage ([string]$Manifest.archive_root)
  New-Item -ItemType Directory -Path $StageSkill -Force | Out-Null
  Get-ChildItem -LiteralPath $BundlePath -Force | Copy-Item -Destination $StageSkill -Recurse -Force
  $Tool = Join-Path $StageSkill 'bin\mo2-tool.exe'
  $ActualVersion = ((& $Tool --version) | Out-String).Trim()
  if ($LASTEXITCODE -ne 0 -or $ActualVersion -ne $Version) { throw "Release Bundle version '$ActualVersion' does not match '$Version'." }
  New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
  $Zip = Join-Path $OutputDirectory $AssetName
  $Checksum = Join-Path $OutputDirectory $ChecksumName
  if (Test-Path -LiteralPath $Zip) { Remove-Item -LiteralPath $Zip -Force }
  if (Test-Path -LiteralPath $Checksum) { Remove-Item -LiteralPath $Checksum -Force }
  Compress-Archive -LiteralPath $StageSkill -DestinationPath $Zip -CompressionLevel Optimal
  $Hash = (Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash.ToLowerInvariant()
  [IO.File]::WriteAllText($Checksum, "$Hash  $AssetName`n", [Text.Encoding]::ASCII)
  [pscustomobject]@{ version=$Version; asset=$Zip; checksum=$Checksum; sha256=$Hash }
} finally {
  $TempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
  $StageFull = [IO.Path]::GetFullPath($Stage)
  if ($StageFull.StartsWith($TempRoot + '\', [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $StageFull)) {
    Remove-Item -LiteralPath $StageFull -Recurse -Force
  }
}
