[CmdletBinding(SupportsShouldProcess)] param(
  [ValidateSet('Codex','Claude','Both')][string]$Target = 'Both',
  [string]$BundlePath,
  [string]$AgentHome = $HOME,
  [string]$LocalAppDataRoot = $env:LOCALAPPDATA
)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if (-not $LocalAppDataRoot) { throw 'LOCALAPPDATA is unavailable; pass -LocalAppDataRoot explicitly.' }
if (-not $BundlePath) {
  $Candidates = @(
    (Join-Path $Root 'mo2-mod-installer'),
    (Join-Path $Root 'skill-bundle\mo2-mod-installer'),
    (Join-Path $Root 'dist\mo2-mod-installer-bundle')
  )
  $BundlePath = $Candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Container } | Select-Object -First 1
}
if (-not $BundlePath -or -not (Test-Path -LiteralPath $BundlePath -PathType Container)) { throw 'A built MO2 Skill Bundle was not found. Run scripts\build.ps1 first or pass -BundlePath.' }
$BundlePath = (Resolve-Path -LiteralPath $BundlePath).Path
$AgentHome = [IO.Path]::GetFullPath($AgentHome)
$ToolkitData = [IO.Path]::GetFullPath((Join-Path $LocalAppDataRoot 'MO2AgentToolkit'))
$BundleParent = Join-Path $ToolkitData 'skill-bundles'
$StableBundle = Join-Path $BundleParent 'mo2-mod-installer'
$BackupRoot = Join-Path $ToolkitData ('adapter-backups\' + (Get-Date -Format 'yyyyMMdd-HHmmssfff'))
$BundleBackupRoot = Join-Path $ToolkitData ('bundle-backups\' + (Get-Date -Format 'yyyyMMdd-HHmmssfff'))
$Manifest = Join-Path $ToolkitData 'adapter-install.json'
$Stage = Join-Path $BundleParent ('.mo2-mod-installer-stage-' + [guid]::NewGuid().ToString('N'))

function Test-PathWithin([string]$Path, [string]$RootPath) {
  $Full = [IO.Path]::GetFullPath($Path); $Base = [IO.Path]::GetFullPath($RootPath)
  return $Full.StartsWith($Base + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}
function Get-LinkTarget([IO.FileSystemInfo]$Item) {
  if (-not $Item.Target) { return $null }
  return [IO.Path]::GetFullPath([string]@($Item.Target)[0])
}
function Remove-Junction([string]$Path) {
  $Item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
  if (-not $Item) { return }
  if ($Item.LinkType -ne 'Junction') { throw "Refusing to remove a non-junction adapter path: $Path" }
  [IO.Directory]::Delete([IO.Path]::GetFullPath($Path), $false)
}
if (-not (Test-PathWithin $StableBundle $ToolkitData)) { throw "Bundle path escaped toolkit data root: $StableBundle" }
$Adapters = @()
if ($Target -in @('Codex','Both')) { $Adapters += [pscustomobject]@{ name='Codex'; root=(Join-Path $AgentHome '.codex\skills'); path=(Join-Path $AgentHome '.codex\skills\mo2-mod-installer') } }
if ($Target -in @('Claude','Both')) { $Adapters += [pscustomobject]@{ name='Claude'; root=(Join-Path $AgentHome '.claude\skills'); path=(Join-Path $AgentHome '.claude\skills\mo2-mod-installer') } }

$AdapterBackups = @(); $CreatedLinks = @(); $ManagedLinks = @(); $OldBundleBackup = $null; $MutationStarted = $false
try {
  New-Item -ItemType Directory -Path $BundleParent -Force | Out-Null
  New-Item -ItemType Directory -Path $Stage | Out-Null
  Get-ChildItem -LiteralPath $BundlePath -Force | Copy-Item -Destination $Stage -Recurse -Force
  $StageExe = Join-Path $Stage 'bin\mo2-tool.exe'
  $RuntimeManifest = Join-Path $Stage 'runtime-manifest.json'
  foreach ($Required in @((Join-Path $Stage 'SKILL.md'), $RuntimeManifest, (Join-Path $Stage 'scripts\ensure-runtime.ps1'), (Join-Path $Stage 'references\agent-contract.md'), $StageExe, (Join-Path $Stage 'bin\_internal'))) {
    if (-not (Test-Path -LiteralPath $Required)) { throw "Incomplete bundle; missing: $Required" }
  }
  $ExpectedVersion = [string]((Get-Content -LiteralPath $RuntimeManifest -Encoding UTF8 -Raw | ConvertFrom-Json).tool_version)
  $Version = ((& $StageExe --version) | Out-String).Trim()
  if ($LASTEXITCODE -ne 0 -or $Version -ne $ExpectedVersion) { throw "Staged bundle version '$Version' does not match manifest '$ExpectedVersion'." }

  if (-not $PSCmdlet.ShouldProcess($StableBundle, 'Install shared MO2 Skill Bundle and adapter junctions')) { return }
  $MutationStarted = $true
  if (Test-Path -LiteralPath $StableBundle) {
    New-Item -ItemType Directory -Path $BundleBackupRoot -Force | Out-Null
    $OldBundleBackup = Join-Path $BundleBackupRoot 'mo2-mod-installer'
    Move-Item -LiteralPath $StableBundle -Destination $OldBundleBackup
  }
  Move-Item -LiteralPath $Stage -Destination $StableBundle

  foreach ($Adapter in $Adapters) {
    $AdapterRoot = [IO.Path]::GetFullPath($Adapter.root)
    $AdapterPath = [IO.Path]::GetFullPath($Adapter.path)
    if (-not (Test-PathWithin $AdapterPath $AdapterRoot)) { throw "Adapter path escaped skill root: $AdapterPath" }
    New-Item -ItemType Directory -Path $AdapterRoot -Force | Out-Null
    $Existing = Get-Item -LiteralPath $AdapterPath -Force -ErrorAction SilentlyContinue
    if ($Existing) {
      $ExistingTarget = Get-LinkTarget $Existing
      if ($Existing.LinkType -eq 'Junction' -and $ExistingTarget -and $ExistingTarget.Equals($StableBundle, [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Junction $AdapterPath
        $ManagedLinks += $AdapterPath
      } else {
        New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null
        $BackupPath = Join-Path $BackupRoot ($Adapter.name.ToLowerInvariant() + '-mo2-mod-installer')
        Move-Item -LiteralPath $AdapterPath -Destination $BackupPath
        $AdapterBackups += [pscustomobject]@{ path=$AdapterPath; backup=$BackupPath }
      }
    }
    New-Item -ItemType Junction -Path $AdapterPath -Target $StableBundle | Out-Null
    $CreatedLinks += $AdapterPath
  }

  $ManagedAdapters = @()
  foreach ($Candidate in @(
    [pscustomobject]@{ name='Codex'; root=(Join-Path $AgentHome '.codex\skills'); path=(Join-Path $AgentHome '.codex\skills\mo2-mod-installer') },
    [pscustomobject]@{ name='Claude'; root=(Join-Path $AgentHome '.claude\skills'); path=(Join-Path $AgentHome '.claude\skills\mo2-mod-installer') }
  )) {
    $CandidateItem = Get-Item -LiteralPath $Candidate.path -Force -ErrorAction SilentlyContinue
    $CandidateTarget = if ($CandidateItem) { Get-LinkTarget $CandidateItem } else { $null }
    if ($CandidateItem -and $CandidateItem.LinkType -eq 'Junction' -and $CandidateTarget -and $CandidateTarget.Equals($StableBundle, [StringComparison]::OrdinalIgnoreCase)) {
      $ManagedAdapters += [ordered]@{ name=$Candidate.name; path=[IO.Path]::GetFullPath($Candidate.path); root=[IO.Path]::GetFullPath($Candidate.root) }
    }
  }
  $ManifestData = [ordered]@{
    schema_version = 1
    bundle = $StableBundle
    tool_version = ([string]$Version).Trim()
    adapters = @($ManagedAdapters)
    installed_at = (Get-Date).ToUniversalTime().ToString('o')
  }
  New-Item -ItemType Directory -Path $ToolkitData -Force | Out-Null
  $ManifestTemp = $Manifest + '.tmp'
  $ManifestData | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ManifestTemp -Encoding UTF8
  Move-Item -LiteralPath $ManifestTemp -Destination $Manifest -Force
  [pscustomobject]@{ bundle=$StableBundle; tool_version=([string]$Version).Trim(); adapters=@($CreatedLinks); adapter_backups=@($AdapterBackups.backup); previous_bundle=$OldBundleBackup }
} catch {
  if ($MutationStarted) {
    foreach ($Link in $CreatedLinks) { Remove-Junction $Link }
    foreach ($Saved in $AdapterBackups) { if (Test-Path -LiteralPath $Saved.backup) { Move-Item -LiteralPath $Saved.backup -Destination $Saved.path } }
    if (Test-Path -LiteralPath $StableBundle) { Remove-Item -LiteralPath $StableBundle -Recurse -Force }
    if ($OldBundleBackup -and (Test-Path -LiteralPath $OldBundleBackup)) { Move-Item -LiteralPath $OldBundleBackup -Destination $StableBundle }
    foreach ($Managed in $ManagedLinks) { if (-not (Get-Item -LiteralPath $Managed -Force -ErrorAction SilentlyContinue)) { New-Item -ItemType Junction -Path $Managed -Target $StableBundle | Out-Null } }
  }
  throw
} finally {
  if (Test-Path -LiteralPath $Stage) { Remove-Item -LiteralPath $Stage -Recurse -Force }
}
