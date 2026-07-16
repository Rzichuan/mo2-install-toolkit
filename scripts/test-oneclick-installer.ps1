$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$RuntimeManifest = Get-Content -LiteralPath (Join-Path $Root 'skills\mo2-mod-installer\runtime-manifest.json') -Encoding UTF8 -Raw | ConvertFrom-Json
$Version = [string]$RuntimeManifest.tool_version
$ReleaseAssets = Join-Path $Root 'release'
$Base = Join-Path $env:TEMP ('mo2-oneclick-test-' + [guid]::NewGuid().ToString('N'))
$DefaultAssets = Join-Path $Base 'default-assets'
$ExplicitAssets = Join-Path $Base 'explicit-assets'
$TestHome = Join-Path $Base 'home'
$TestLocal = Join-Path $Base 'local'
$InstallerManifestName = 'mo2-installer-manifest.json'
$InstallerManifestText = $null
$InstallerManifest = $null

function ConvertTo-SingleQuotedLiteral([string]$Value) {
  return "'" + $Value.Replace("'", "''") + "'"
}
function Replace-ExactlyOnce([string]$Content, [string]$Old, [string]$New) {
  if ([regex]::Matches($Content, [regex]::Escape($Old)).Count -ne 1) {
    throw "Expected exactly one installer test substitution for: $Old"
  }
  return $Content.Replace($Old, $New)
}
function Write-Utf8NoBom([string]$Path, [string]$Content) {
  [IO.File]::WriteAllText($Path, $Content, [Text.UTF8Encoding]::new($false))
}
function New-ManifestVariant([scriptblock]$Mutator) {
  $Data = $InstallerManifestText | ConvertFrom-Json
  & $Mutator $Data | Out-Null
  return (($Data | ConvertTo-Json -Depth 6) + "`n")
}
function Invoke-InstallerViaExpression([string]$IexAgentHome, [string]$IexLocalAppDataRoot) {
  $Content = Get-Content -LiteralPath (Join-Path $Root 'install.ps1') -Encoding UTF8 -Raw
  $Content = Replace-ExactlyOnce $Content '[string]$AgentHome = $HOME,' ("[string]`$AgentHome = " + (ConvertTo-SingleQuotedLiteral $IexAgentHome) + ',')
  $Content = Replace-ExactlyOnce $Content '[string]$LocalAppDataRoot = $env:LOCALAPPDATA,' ("[string]`$LocalAppDataRoot = " + (ConvertTo-SingleQuotedLiteral $IexLocalAppDataRoot) + ',')
  $Content = Replace-ExactlyOnce $Content '  [string]$AssetDirectory' ("  [string]`$AssetDirectory = " + (ConvertTo-SingleQuotedLiteral $DefaultAssets))
  $Content | Invoke-Expression
}
function Invoke-UninstallerViaExpression([string]$IexLocalAppDataRoot) {
  $Content = Get-Content -LiteralPath (Join-Path $Root 'uninstall.ps1') -Encoding UTF8 -Raw
  $Content = Replace-ExactlyOnce $Content '[string]$LocalAppDataRoot = $env:LOCALAPPDATA,' ("[string]`$LocalAppDataRoot = " + (ConvertTo-SingleQuotedLiteral $IexLocalAppDataRoot) + ',')
  $Content = Replace-ExactlyOnce $Content '  [switch]$RemoveRuntime' '  [switch]$RemoveRuntime = $true'
  $Content | Invoke-Expression
}
function Assert-DefaultManifestFailure(
  [string]$Name,
  [string]$ManifestContent,
  [switch]$CopyZipAssets
) {
  $CaseRoot = Join-Path $Base ("invalid-$Name")
  $CaseAssets = Join-Path $CaseRoot 'assets'
  $CaseHome = Join-Path $CaseRoot 'home'
  $CaseLocal = Join-Path $CaseRoot 'local'
  New-Item -ItemType Directory -Path $CaseAssets, (Join-Path $CaseHome '.codex'), $CaseLocal -Force | Out-Null
  Write-Utf8NoBom (Join-Path $CaseAssets $InstallerManifestName) $ManifestContent
  if ($CopyZipAssets) {
    foreach ($AssetName in @([string]$InstallerManifest.skill_asset_name, [string]$InstallerManifest.runtime_asset_name)) {
      Copy-Item -LiteralPath (Join-Path $DefaultAssets $AssetName) -Destination (Join-Path $CaseAssets $AssetName) -Force
    }
  }
  $Failed = $false
  $FailureMessage = ''
  try {
    & (Join-Path $Root 'install.ps1') -Target Codex -AgentHome $CaseHome -LocalAppDataRoot $CaseLocal -AssetDirectory $CaseAssets | Out-Null
  } catch {
    $Failed = $true
    $FailureMessage = $_.Exception.Message
  }
  if (-not $Failed) { throw "Invalid installer manifest case '$Name' unexpectedly succeeded." }
  if ($FailureMessage -notmatch 'Use a tagged installer' -or $FailureMessage -notmatch 'no GitHub API fallback') {
    throw "Invalid installer manifest case '$Name' did not provide pinned-install guidance: $FailureMessage"
  }
  if (Test-Path -LiteralPath (Join-Path $CaseLocal 'MO2AgentToolkit')) {
    throw "Invalid installer manifest case '$Name' modified the toolkit data root."
  }
  if (Test-Path -LiteralPath (Join-Path $CaseHome '.codex\skills\mo2-mod-installer')) {
    throw "Invalid installer manifest case '$Name' created a Codex adapter."
  }
}

try {
  New-Item -ItemType Directory -Path $DefaultAssets, $ExplicitAssets, $TestHome, $TestLocal -Force | Out-Null
  $SourceInstallerManifest = Join-Path $ReleaseAssets $InstallerManifestName
  if (-not (Test-Path -LiteralPath $SourceInstallerManifest -PathType Leaf)) {
    throw "Packaged installer manifest not found: $SourceInstallerManifest"
  }
  $InstallerManifestText = [IO.File]::ReadAllText($SourceInstallerManifest, [Text.UTF8Encoding]::new($false, $true))
  $InstallerManifest = $InstallerManifestText | ConvertFrom-Json
  if ([string]$InstallerManifest.toolkit_version -ne $Version) { throw 'Packaged installer manifest version mismatch.' }

  Copy-Item -LiteralPath $SourceInstallerManifest -Destination (Join-Path $DefaultAssets $InstallerManifestName) -Force
  foreach ($AssetName in @([string]$InstallerManifest.skill_asset_name, [string]$InstallerManifest.runtime_asset_name)) {
    Copy-Item -LiteralPath (Join-Path $ReleaseAssets $AssetName) -Destination (Join-Path $DefaultAssets $AssetName) -Force
    Copy-Item -LiteralPath (Join-Path $ReleaseAssets $AssetName) -Destination (Join-Path $ExplicitAssets $AssetName) -Force
    Copy-Item -LiteralPath (Join-Path $ReleaseAssets "$AssetName.sha256") -Destination (Join-Path $ExplicitAssets "$AssetName.sha256") -Force
  }
  if (Get-ChildItem -LiteralPath $DefaultAssets -Filter '*.sha256' -File) { throw 'Default-install fixture unexpectedly contains checksum sidecars.' }
  if (Test-Path -LiteralPath (Join-Path $ExplicitAssets $InstallerManifestName)) { throw 'Explicit-version fixture unexpectedly contains an installer manifest.' }

  Assert-DefaultManifestFailure 'corrupt-json' "{`n"
  Assert-DefaultManifestFailure 'tag-version-mismatch' (New-ManifestVariant { param($Data) $Data.release_tag = 'v9.9.9' })
  Assert-DefaultManifestFailure 'wrong-platform' (New-ManifestVariant { param($Data) $Data.platform = 'linux-x64' })
  Assert-DefaultManifestFailure 'abnormal-asset-name' (New-ManifestVariant { param($Data) $Data.skill_asset_name = '..\unexpected.zip' })
  Assert-DefaultManifestFailure 'invalid-hash-format' (New-ManifestVariant { param($Data) $Data.skill_sha256 = 'not-a-sha256' })
  Assert-DefaultManifestFailure 'wrong-hash' (New-ManifestVariant { param($Data) $Data.skill_sha256 = ('0' * 64) }) -CopyZipAssets

  $DetectionFailed = $false
  try {
    & (Join-Path $Root 'install.ps1') -Target Auto -AgentHome $TestHome -LocalAppDataRoot $TestLocal -AssetDirectory $DefaultAssets | Out-Null
  } catch {
    $DetectionFailed = $true
  }
  if (-not $DetectionFailed) { throw 'Auto installation accepted a home with neither client.' }

  foreach ($Agent in @('.codex', '.claude')) {
    $Old = Join-Path $TestHome "$Agent\skills\mo2-mod-installer"
    New-Item -ItemType Directory -Path $Old -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $Old 'old-marker.txt') -Value $Agent -Encoding UTF8
  }

  & (Join-Path $Root 'install.ps1') -Target Auto -AgentHome $TestHome -LocalAppDataRoot $TestLocal -AssetDirectory $DefaultAssets -WhatIf | Out-Null
  if (Test-Path -LiteralPath (Join-Path $TestLocal 'MO2AgentToolkit')) { throw 'Installer -WhatIf changed the toolkit data root.' }
  foreach ($Agent in @('.codex', '.claude')) {
    if (-not (Test-Path -LiteralPath (Join-Path $TestHome "$Agent\skills\mo2-mod-installer\old-marker.txt") -PathType Leaf)) {
      throw "Installer -WhatIf changed the existing $Agent Skill."
    }
  }

  Invoke-InstallerViaExpression $TestHome $TestLocal | Out-Null
  & (Join-Path $Root 'install.ps1') -Version $Version -Target Codex -AgentHome $TestHome -LocalAppDataRoot $TestLocal -AssetDirectory $ExplicitAssets | Out-Null

  foreach ($Agent in @('.codex', '.claude')) {
    $Link = Join-Path $TestHome "$Agent\skills\mo2-mod-installer"
    $Item = Get-Item -LiteralPath $Link -Force
    if ($Item.LinkType -ne 'Junction') { throw "Expected Junction: $Link" }
  }
  $Data = Get-Content -LiteralPath (Join-Path $TestLocal 'MO2AgentToolkit\adapter-install.json') -Encoding UTF8 -Raw | ConvertFrom-Json
  if ([string]$Data.tool_version -ne $Version) { throw 'Default manifest installation selected the wrong version.' }
  if (@($Data.adapters).Count -ne 2) { throw 'Targeted reinstall lost an existing managed adapter.' }
  $Markers = @(Get-ChildItem -LiteralPath (Join-Path $TestLocal 'MO2AgentToolkit\adapter-backups') -Filter old-marker.txt -File -Recurse)
  if ($Markers.Count -ne 2) { throw 'Existing user Skills were not backed up.' }
  $Actual = ((& (Join-Path ([string]$Data.runtime) 'bin\mo2-tool.exe') --version) | Out-String).Trim()
  if ($Actual -ne $Version) { throw "Installed runtime mismatch: $Actual" }

  & (Join-Path $Root 'uninstall.ps1') -LocalAppDataRoot $TestLocal -RemoveRuntime -WhatIf | Out-Null
  foreach ($ManagedPath in @([string]$Data.bundle, [string]$Data.runtime, (Join-Path $TestLocal 'MO2AgentToolkit\adapter-install.json'))) {
    if (-not (Test-Path -LiteralPath $ManagedPath)) { throw "Uninstaller -WhatIf removed a managed path: $ManagedPath" }
  }
  foreach ($Agent in @('.codex', '.claude')) {
    if (-not (Test-Path -LiteralPath (Join-Path $TestHome "$Agent\skills\mo2-mod-installer"))) { throw "Uninstaller -WhatIf removed the $Agent adapter." }
  }

  Invoke-UninstallerViaExpression $TestLocal | Out-Null
  foreach ($Agent in @('.codex', '.claude')) {
    if (Test-Path -LiteralPath (Join-Path $TestHome "$Agent\skills\mo2-mod-installer")) { throw "$Agent adapter remains after IEX uninstall." }
  }
  foreach ($ManagedPath in @([string]$Data.bundle, [string]$Data.runtime, (Join-Path $TestLocal 'MO2AgentToolkit\adapter-install.json'))) {
    if (Test-Path -LiteralPath $ManagedPath) { throw "Managed path remains after IEX uninstall: $ManagedPath" }
  }

  $RollbackHome = Join-Path $Base 'rollback-home'
  $RollbackLocal = Join-Path $Base 'rollback-local'
  $RollbackToolkit = Join-Path $RollbackLocal 'MO2AgentToolkit'
  $OldStableSkill = Join-Path $RollbackToolkit 'skill-bundles\mo2-mod-installer'
  $RuntimeVersions = Join-Path $RollbackToolkit 'runtimes'
  New-Item -ItemType Directory -Path (Join-Path $RollbackHome '.codex'), $OldStableSkill, $RuntimeVersions -Force | Out-Null
  Set-Content -LiteralPath (Join-Path $OldStableSkill 'old-marker.txt') -Value 'preserve-me' -Encoding UTF8
  Set-Content -LiteralPath (Join-Path $RuntimeVersions $Version) -Value 'blocks runtime directory creation' -Encoding UTF8
  $RollbackFailed = $false
  try {
    & (Join-Path $Root 'install.ps1') -Version $Version -Target Codex -AgentHome $RollbackHome -LocalAppDataRoot $RollbackLocal -AssetDirectory $ExplicitAssets | Out-Null
  } catch {
    $RollbackFailed = $true
  }
  if (-not $RollbackFailed) { throw 'Rollback fixture did not make installation fail.' }
  if (-not (Test-Path -LiteralPath (Join-Path $OldStableSkill 'old-marker.txt') -PathType Leaf)) { throw 'Failed installation deleted the previous managed Skill.' }
  if (Test-Path -LiteralPath (Join-Path $RollbackHome '.codex\skills\mo2-mod-installer')) { throw 'Failed installation left a new adapter behind.' }

  Write-Output "One-command installer integration test passed for $Version on Windows PowerShell $($PSVersionTable.PSVersion)."
} finally {
  $Temp = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\')
  $Full = [IO.Path]::GetFullPath($Base)
  if ($Full.StartsWith($Temp + '\', [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $Full)) {
    Remove-Item -LiteralPath $Full -Recurse -Force
  }
}
