[CmdletBinding()] param(
  [string]$ToolDirectory,
  [string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if (-not $ToolDirectory) { $ToolDirectory = Join-Path $Root 'dist\mo2-tool' }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $Root 'release' }
$ToolDirectory = (Resolve-Path -LiteralPath $ToolDirectory).Path
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$Manifest = Get-Content -LiteralPath (Join-Path $Root 'skills\mo2-mod-installer\runtime-manifest.json') -Encoding UTF8 -Raw | ConvertFrom-Json
$Version = [string]$Manifest.tool_version
$Platform = [string]$Manifest.platform
$ArchiveRoot = [string]$Manifest.archive_root
$AssetName = [string]$Manifest.asset_name
$ChecksumName = [string]$Manifest.checksum_asset_name
$ReleaseTag = "v$Version"
$SkillAssetName = "mo2-skill-$ReleaseTag.zip"
$SkillChecksumName = "$SkillAssetName.sha256"
$InstallerManifestName = 'mo2-installer-manifest.json'
$ReleaseBaseUri = "https://github.com/Rzichuan/mo2-install-toolkit/releases/download/$ReleaseTag"
if ([string]$Manifest.schema_version -cne '1') { throw 'Unsupported runtime manifest schema.' }
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "Invalid runtime version: $Version" }
if ([string]$Manifest.toolkit_version -cne $Version) { throw 'Toolkit and runtime manifest versions differ.' }
if ($Platform -cne 'win-x64') { throw "Unexpected runtime platform: $Platform" }
if ([string]$Manifest.release_tag -cne $ReleaseTag) { throw "Unexpected release tag: $($Manifest.release_tag)" }
if ($ArchiveRoot -cne 'mo2-runtime') { throw "Unexpected runtime archive root: $ArchiveRoot" }
if ($AssetName -cne "mo2-runtime-$ReleaseTag-win-x64.zip") { throw "Unexpected runtime asset name: $AssetName" }
if ($ChecksumName -cne "$AssetName.sha256") { throw "Unexpected checksum asset name: $ChecksumName" }
if ([string]$Manifest.asset_url -cne "$ReleaseBaseUri/$AssetName") { throw 'Unexpected runtime asset URL.' }
if ([string]$Manifest.checksum_url -cne "$ReleaseBaseUri/$ChecksumName") { throw 'Unexpected runtime checksum URL.' }
$SourceTool = Join-Path $ToolDirectory 'mo2-tool.exe'
$SourceInternal = Join-Path $ToolDirectory '_internal'
if (-not (Test-Path -LiteralPath $SourceTool -PathType Leaf)) { throw "Tool executable not found: $SourceTool" }
if (-not (Test-Path -LiteralPath $SourceInternal -PathType Container)) { throw "PyInstaller _internal directory not found: $SourceInternal" }
$Stage = Join-Path ([IO.Path]::GetTempPath()) ('mo2-runtime-stage-' + [guid]::NewGuid().ToString('N'))
try {
  $StageRuntime = Join-Path $Stage $ArchiveRoot
  $StageSkill = Join-Path $Stage 'mo2-skill'
  $StageBin = Join-Path $StageRuntime 'bin'
  New-Item -ItemType Directory -Path $StageBin -Force | Out-Null
  New-Item -ItemType Directory -Path $StageSkill -Force | Out-Null
  Get-ChildItem -LiteralPath (Join-Path $Root 'skills\mo2-mod-installer') -Force | Copy-Item -Destination $StageSkill -Recurse -Force
  Copy-Item -LiteralPath (Join-Path $Root 'LICENSE') -Destination $StageSkill -Force
  Copy-Item -LiteralPath (Join-Path $Root 'THIRD_PARTY_NOTICES.md') -Destination $StageSkill -Force
  $SkillMetadata = [ordered]@{ schema_version=1; toolkit_version=$Version; platform=$Platform } | ConvertTo-Json
  [IO.File]::WriteAllText((Join-Path $StageSkill 'skill.json'), $SkillMetadata + "`n", [Text.UTF8Encoding]::new($false))
  Get-ChildItem -LiteralPath $ToolDirectory -Force | Copy-Item -Destination $StageBin -Recurse -Force
  Copy-Item -LiteralPath (Join-Path $Root 'LICENSE') -Destination $StageRuntime -Force
  Copy-Item -LiteralPath (Join-Path $Root 'THIRD_PARTY_NOTICES.md') -Destination $StageRuntime -Force
  $ThirdPartyDestination = Join-Path $StageRuntime 'third_party'
  New-Item -ItemType Directory -Path $ThirdPartyDestination -Force | Out-Null
  Get-ChildItem -LiteralPath (Join-Path $Root 'third_party') -Force | Copy-Item -Destination $ThirdPartyDestination -Recurse -Force
  $RuntimeMetadata = [ordered]@{
    schema_version = 1
    tool_version = $Version
    platform = $Platform
  } | ConvertTo-Json
  [IO.File]::WriteAllText((Join-Path $StageRuntime 'runtime.json'), $RuntimeMetadata + "`n", [Text.UTF8Encoding]::new($false))
  foreach ($Required in @(
    (Join-Path $StageSkill 'skill.json'),
    (Join-Path $StageSkill 'SKILL.md'),
    (Join-Path $StageSkill 'runtime-manifest.json'),
    (Join-Path $StageSkill 'scripts\ensure-runtime.ps1'),
    (Join-Path $StageRuntime 'runtime.json'),
    (Join-Path $StageRuntime 'LICENSE'),
    (Join-Path $StageRuntime 'THIRD_PARTY_NOTICES.md'),
    (Join-Path $StageRuntime 'third_party\pyfomod\LICENSE'),
    (Join-Path $StageRuntime 'third_party\mutagen\LICENSE'),
    (Join-Path $StageRuntime 'third_party\newtonsoft-json\LICENSE.md'),
    (Join-Path $StageBin 'mo2-tool.exe'),
    (Join-Path $StageBin '_internal')
  )) {
    if (-not (Test-Path -LiteralPath $Required)) { throw "Incomplete runtime payload; missing: $Required" }
  }
  $Tool = Join-Path $StageBin 'mo2-tool.exe'
  $ActualVersion = ((& $Tool --version) | Out-String).Trim()
  if ($LASTEXITCODE -ne 0 -or $ActualVersion -ne $Version) { throw "Runtime version '$ActualVersion' does not match '$Version'." }
  New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
  $Zip = Join-Path $OutputDirectory $AssetName
  $Checksum = Join-Path $OutputDirectory $ChecksumName
  $SkillZip = Join-Path $OutputDirectory $SkillAssetName
  $SkillChecksum = Join-Path $OutputDirectory $SkillChecksumName
  $InstallerManifestPath = Join-Path $OutputDirectory $InstallerManifestName
  $ObsoleteBundle = Join-Path $OutputDirectory "mo2-mod-installer-v$Version-win-x64.zip"
  $ObsoleteChecksum = "$ObsoleteBundle.sha256"
  foreach ($PreviousAsset in @($Zip, $Checksum, $SkillZip, $SkillChecksum, $InstallerManifestPath, $ObsoleteBundle, $ObsoleteChecksum)) {
    if (Test-Path -LiteralPath $PreviousAsset -PathType Leaf) { Remove-Item -LiteralPath $PreviousAsset -Force }
  }
  Compress-Archive -LiteralPath $StageRuntime -DestinationPath $Zip -CompressionLevel Optimal
  Compress-Archive -LiteralPath $StageSkill -DestinationPath $SkillZip -CompressionLevel Optimal
  $Stream = [IO.File]::OpenRead($Zip)
  $Sha256 = [Security.Cryptography.SHA256]::Create()
  try { $Hash = ([BitConverter]::ToString($Sha256.ComputeHash($Stream))).Replace('-', '').ToLowerInvariant() }
  finally { $Sha256.Dispose(); $Stream.Dispose() }
  [IO.File]::WriteAllText($Checksum, "$Hash  $AssetName`n", [Text.Encoding]::ASCII)
  $SkillStream = [IO.File]::OpenRead($SkillZip)
  $SkillSha256 = [Security.Cryptography.SHA256]::Create()
  try { $SkillHash = ([BitConverter]::ToString($SkillSha256.ComputeHash($SkillStream))).Replace('-', '').ToLowerInvariant() }
  finally { $SkillSha256.Dispose(); $SkillStream.Dispose() }
  [IO.File]::WriteAllText($SkillChecksum, "$SkillHash  $SkillAssetName`n", [Text.Encoding]::ASCII)
  $InstallerManifestData = [ordered]@{
    schema_version = 1
    toolkit_version = $Version
    release_tag = $ReleaseTag
    platform = $Platform
    skill_asset_name = $SkillAssetName
    skill_sha256 = $SkillHash
    runtime_asset_name = $AssetName
    runtime_sha256 = $Hash
  }
  $InstallerManifestJson = $InstallerManifestData | ConvertTo-Json
  [IO.File]::WriteAllText($InstallerManifestPath, $InstallerManifestJson + "`n", [Text.UTF8Encoding]::new($false))
  [pscustomobject]@{ version=$Version; runtime_asset=$Zip; runtime_checksum=$Checksum; runtime_sha256=$Hash; skill_asset=$SkillZip; skill_checksum=$SkillChecksum; skill_sha256=$SkillHash; installer_manifest=$InstallerManifestPath }
} finally {
  $TempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
  $StageFull = [IO.Path]::GetFullPath($Stage)
  if ($StageFull.StartsWith($TempRoot + '\', [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $StageFull)) {
    Remove-Item -LiteralPath $StageFull -Recurse -Force
  }
}
