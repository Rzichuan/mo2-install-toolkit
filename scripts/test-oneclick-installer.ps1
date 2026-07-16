$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Manifest = Get-Content -LiteralPath (Join-Path $Root 'skills\mo2-mod-installer\runtime-manifest.json') -Encoding UTF8 -Raw | ConvertFrom-Json
$Version = [string]$Manifest.tool_version
$Assets = Join-Path $Root 'release'
$Base = Join-Path $env:TEMP ('mo2-oneclick-test-' + [guid]::NewGuid().ToString('N'))
$TestHome = Join-Path $Base 'home'
$TestLocal = Join-Path $Base 'local'

function ConvertTo-SingleQuotedLiteral([string]$Value) {
  return "'" + $Value.Replace("'", "''") + "'"
}
function Replace-ExactlyOnce([string]$Content, [string]$Old, [string]$New) {
  if ([regex]::Matches($Content, [regex]::Escape($Old)).Count -ne 1) {
    throw "Expected exactly one installer test substitution for: $Old"
  }
  return $Content.Replace($Old, $New)
}
function Invoke-InstallerViaExpression([string]$IexAgentHome, [string]$IexLocalAppDataRoot) {
  $Content = Get-Content -LiteralPath (Join-Path $Root 'install.ps1') -Encoding UTF8 -Raw
  $Content = Replace-ExactlyOnce $Content '[string]$Version,' ("[string]`$Version = " + (ConvertTo-SingleQuotedLiteral $Version) + ',')
  $Content = Replace-ExactlyOnce $Content '[string]$AgentHome = $HOME,' ("[string]`$AgentHome = " + (ConvertTo-SingleQuotedLiteral $IexAgentHome) + ',')
  $Content = Replace-ExactlyOnce $Content '[string]$LocalAppDataRoot = $env:LOCALAPPDATA,' ("[string]`$LocalAppDataRoot = " + (ConvertTo-SingleQuotedLiteral $IexLocalAppDataRoot) + ',')
  $Content = Replace-ExactlyOnce $Content '  [string]$AssetDirectory' ("  [string]`$AssetDirectory = " + (ConvertTo-SingleQuotedLiteral $Assets))
  $Content | Invoke-Expression
}
function Invoke-UninstallerViaExpression([string]$IexLocalAppDataRoot) {
  $Content = Get-Content -LiteralPath (Join-Path $Root 'uninstall.ps1') -Encoding UTF8 -Raw
  $Content = Replace-ExactlyOnce $Content '[string]$LocalAppDataRoot = $env:LOCALAPPDATA,' ("[string]`$LocalAppDataRoot = " + (ConvertTo-SingleQuotedLiteral $IexLocalAppDataRoot) + ',')
  $Content = Replace-ExactlyOnce $Content '  [switch]$RemoveRuntime' '  [switch]$RemoveRuntime = $true'
  $Content | Invoke-Expression
}

try {
  New-Item -ItemType Directory -Path $TestHome, $TestLocal -Force | Out-Null

  $DetectionFailed = $false
  try {
    & (Join-Path $Root 'install.ps1') -Version $Version -Target Auto -AgentHome $TestHome -LocalAppDataRoot $TestLocal -AssetDirectory $Assets | Out-Null
  } catch {
    $DetectionFailed = $true
  }
  if (-not $DetectionFailed) { throw 'Auto installation accepted a home with neither client.' }

  foreach ($Agent in @('.codex', '.claude')) {
    $Old = Join-Path $TestHome "$Agent\skills\mo2-mod-installer"
    New-Item -ItemType Directory -Path $Old -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $Old 'old-marker.txt') -Value $Agent -Encoding UTF8
  }

  & (Join-Path $Root 'install.ps1') -Version $Version -Target Auto -AgentHome $TestHome -LocalAppDataRoot $TestLocal -AssetDirectory $Assets -WhatIf | Out-Null
  if (Test-Path -LiteralPath (Join-Path $TestLocal 'MO2AgentToolkit')) { throw 'Installer -WhatIf changed the toolkit data root.' }
  foreach ($Agent in @('.codex', '.claude')) {
    if (-not (Test-Path -LiteralPath (Join-Path $TestHome "$Agent\skills\mo2-mod-installer\old-marker.txt") -PathType Leaf)) {
      throw "Installer -WhatIf changed the existing $Agent Skill."
    }
  }

  Invoke-InstallerViaExpression $TestHome $TestLocal | Out-Null
  & (Join-Path $Root 'install.ps1') -Version $Version -Target Codex -AgentHome $TestHome -LocalAppDataRoot $TestLocal -AssetDirectory $Assets | Out-Null

  foreach ($Agent in @('.codex', '.claude')) {
    $Link = Join-Path $TestHome "$Agent\skills\mo2-mod-installer"
    $Item = Get-Item -LiteralPath $Link -Force
    if ($Item.LinkType -ne 'Junction') { throw "Expected Junction: $Link" }
  }
  $Data = Get-Content -LiteralPath (Join-Path $TestLocal 'MO2AgentToolkit\adapter-install.json') -Encoding UTF8 -Raw | ConvertFrom-Json
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
    & (Join-Path $Root 'install.ps1') -Version $Version -Target Codex -AgentHome $RollbackHome -LocalAppDataRoot $RollbackLocal -AssetDirectory $Assets | Out-Null
  } catch {
    $RollbackFailed = $true
  }
  if (-not $RollbackFailed) { throw 'Rollback fixture did not make installation fail.' }
  if (-not (Test-Path -LiteralPath (Join-Path $OldStableSkill 'old-marker.txt') -PathType Leaf)) { throw 'Failed installation deleted the previous managed Skill.' }
  if (Test-Path -LiteralPath (Join-Path $RollbackHome '.codex\skills\mo2-mod-installer')) { throw 'Failed installation left a new adapter behind.' }

  Write-Output "One-command installer integration test passed for $Version."
} finally {
  $Temp = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\')
  $Full = [IO.Path]::GetFullPath($Base)
  if ($Full.StartsWith($Temp + '\', [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $Full)) {
    Remove-Item -LiteralPath $Full -Recurse -Force
  }
}
