$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Bundle = (Resolve-Path -LiteralPath (Join-Path $Root 'dist\mo2-mod-installer-bundle')).Path
$TempBase = [IO.Path]::GetFullPath((Join-Path $env:TEMP ('mo2-adapter-test-' + [guid]::NewGuid().ToString('N'))))
$HomePath = Join-Path $TempBase 'home'
$LocalPath = Join-Path $TempBase 'local'
try {
  foreach ($Agent in @('.codex', '.claude')) {
    $OldSkill = Join-Path $HomePath "$Agent\skills\mo2-mod-installer"
    New-Item -ItemType Directory -Path $OldSkill -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $OldSkill 'old-marker.txt') -Value $Agent -Encoding UTF8
  }
  & (Join-Path $Root 'scripts\install-adapters.ps1') -Target Both -BundlePath $Bundle -AgentHome $HomePath -LocalAppDataRoot $LocalPath | Out-Null
  $Stable = Join-Path $LocalPath 'MO2AgentToolkit\skill-bundles\mo2-mod-installer'
  foreach ($Agent in @('.codex', '.claude')) {
    $Link = Join-Path $HomePath "$Agent\skills\mo2-mod-installer"
    $Item = Get-Item -LiteralPath $Link -Force
    if ($Item.LinkType -ne 'Junction') { throw "Expected Junction: $Link" }
    $Target = [IO.Path]::GetFullPath([string]@($Item.Target)[0])
    if (-not $Target.Equals([IO.Path]::GetFullPath($Stable), [StringComparison]::OrdinalIgnoreCase)) { throw "Unexpected Junction target: $Target" }
  }
  $Unrelated = Join-Path $TempBase 'unrelated-working-directory'
  New-Item -ItemType Directory -Path $Unrelated | Out-Null
  Push-Location $Unrelated
  try { $Version = & (Join-Path $HomePath '.claude\skills\mo2-mod-installer\bin\mo2-tool.exe') --version }
  finally { Pop-Location }
  if ($LASTEXITCODE -ne 0 -or -not $Version) { throw 'Installed Bundle smoke test failed' }
  $BackedUpMarkers = @(Get-ChildItem -LiteralPath (Join-Path $LocalPath 'MO2AgentToolkit\adapter-backups') -Filter old-marker.txt -File -Recurse)
  if ($BackedUpMarkers.Count -ne 2) { throw "Expected two migrated adapter backups, got $($BackedUpMarkers.Count)" }

  # Reinstall exercises stable Bundle replacement while both Junctions already exist.
  & (Join-Path $Root 'scripts\install-adapters.ps1') -Target Both -BundlePath $Bundle -AgentHome $HomePath -LocalAppDataRoot $LocalPath | Out-Null
  $InternalCopies = @(Get-ChildItem -LiteralPath (Join-Path $LocalPath 'MO2AgentToolkit\skill-bundles') -Directory -Recurse | Where-Object Name -eq '_internal')
  if ($InternalCopies.Count -ne 1) { throw "Expected one active _internal runtime, got $($InternalCopies.Count)" }
  & (Join-Path $Root 'scripts\install-adapters.ps1') -Target Claude -BundlePath $Bundle -AgentHome $HomePath -LocalAppDataRoot $LocalPath | Out-Null
  $Recorded = Get-Content -LiteralPath (Join-Path $LocalPath 'MO2AgentToolkit\adapter-install.json') -Encoding UTF8 -Raw | ConvertFrom-Json
  if (@($Recorded.adapters).Count -ne 2) { throw 'A targeted update lost the other managed adapter from the manifest' }

  # Invalid input must fail before changing the managed installation.
  $Invalid = Join-Path $TempBase 'invalid-bundle'
  New-Item -ItemType Directory -Path $Invalid | Out-Null
  Set-Content -LiteralPath (Join-Path $Invalid 'SKILL.md') -Value '# invalid' -Encoding UTF8
  $Failed = $false
  try { & (Join-Path $Root 'scripts\install-adapters.ps1') -Target Both -BundlePath $Invalid -AgentHome $HomePath -LocalAppDataRoot $LocalPath | Out-Null }
  catch { $Failed = $true }
  if (-not $Failed) { throw 'Invalid Bundle installation unexpectedly succeeded' }
  if (-not (Test-Path -LiteralPath (Join-Path $HomePath '.claude\skills\mo2-mod-installer\bin\mo2-tool.exe'))) { throw 'Existing installation changed after invalid update' }

  # Uninstall preflights every recorded adapter before removing any of them.
  $ClaudeLink = Join-Path $HomePath '.claude\skills\mo2-mod-installer'
  Remove-Item -LiteralPath $ClaudeLink -Force
  New-Item -ItemType Directory -Path $ClaudeLink | Out-Null
  $UninstallFailed = $false
  try { & (Join-Path $Root 'scripts\uninstall-adapters.ps1') -LocalAppDataRoot $LocalPath | Out-Null }
  catch { $UninstallFailed = $true }
  if (-not $UninstallFailed) { throw 'Uninstall accepted a changed adapter' }
  if ((Get-Item -LiteralPath (Join-Path $HomePath '.codex\skills\mo2-mod-installer') -Force).LinkType -ne 'Junction') { throw 'Uninstall partially removed adapters before validation completed' }
  Remove-Item -LiteralPath $ClaudeLink -Recurse -Force
  New-Item -ItemType Junction -Path $ClaudeLink -Target $Stable | Out-Null

  & (Join-Path $Root 'scripts\uninstall-adapters.ps1') -LocalAppDataRoot $LocalPath | Out-Null
  foreach ($Agent in @('.codex', '.claude')) {
    if (Test-Path -LiteralPath (Join-Path $HomePath "$Agent\skills\mo2-mod-installer")) { throw "Adapter still exists after uninstall: $Agent" }
  }
  if (Test-Path -LiteralPath $Stable) { throw 'Stable Bundle still exists after uninstall' }
  if (-not (Test-Path -LiteralPath (Join-Path $LocalPath 'MO2AgentToolkit\adapter-backups'))) { throw 'Adapter backups were unexpectedly removed' }
  Write-Output "Adapter integration test passed for mo2-tool $(([string]$Version).Trim())"
} finally {
  $TempRoot = [IO.Path]::GetFullPath($env:TEMP)
  if ($TempBase.StartsWith($TempRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $TempBase)) {
    Remove-Item -LiteralPath $TempBase -Recurse -Force
  }
}
