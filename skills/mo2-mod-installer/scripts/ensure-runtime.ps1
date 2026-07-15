[CmdletBinding()]
param(
  [switch]$Json,
  [string]$ManifestPath,
  [string]$CacheRoot,
  [string]$LegacyBundlePath,
  [switch]$AllowInsecureTestUrls
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$script:Warnings = New-Object System.Collections.Generic.List[string]
$script:StagePath = $null
$script:Mutex = $null
$script:MutexHeld = $false

function Write-Outcome {
  param(
    [string]$Status,
    [int]$ExitCode,
    [string]$ToolVersion,
    [string]$ToolPath,
    [bool]$Downloaded,
    [string]$CacheSource,
    [string[]]$Errors = @()
  )
  $payload = [ordered]@{
    schema_version = 1
    status = $Status
    tool_version = $ToolVersion
    tool_path = $ToolPath
    downloaded = $Downloaded
    cache_source = $CacheSource
    warnings = @($script:Warnings)
    errors = @($Errors)
  }
  if ($Json) {
    $payload | ConvertTo-Json -Depth 5 -Compress
  } else {
    $payload | ConvertTo-Json -Depth 5
  }
  exit $ExitCode
}

function Stop-Bootstrap {
  param([int]$ExitCode, [string]$Message, [string]$ToolVersion = '')
  Write-Outcome -Status 'error' -ExitCode $ExitCode -ToolVersion $ToolVersion -ToolPath '' -Downloaded $false -CacheSource '' -Errors @($Message)
}

function Test-ChildPath {
  param([string]$Path, [string]$Root)
  $full = [IO.Path]::GetFullPath($Path)
  $base = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
  return $full.StartsWith($base + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}

function Test-ExpectedRuntime {
  param([string]$Root, [string]$ExpectedVersion)
  if (-not $Root -or -not (Test-Path -LiteralPath $Root -PathType Container)) {
    return [pscustomobject]@{ Valid = $false; Path = ''; Version = ''; Reason = 'directory_missing' }
  }
  $exe = Join-Path $Root 'bin\mo2-tool.exe'
  $internal = Join-Path $Root 'bin\_internal'
  $skill = Join-Path $Root 'SKILL.md'
  if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    return [pscustomobject]@{ Valid = $false; Path = $exe; Version = ''; Reason = 'executable_missing' }
  }
  if (-not (Test-Path -LiteralPath $internal -PathType Container)) {
    return [pscustomobject]@{ Valid = $false; Path = $exe; Version = ''; Reason = 'internal_missing' }
  }
  if (-not (Test-Path -LiteralPath $skill -PathType Leaf)) {
    return [pscustomobject]@{ Valid = $false; Path = $exe; Version = ''; Reason = 'skill_missing' }
  }
  try {
    $versionLines = @(& $exe --version 2>$null)
    $exit = $LASTEXITCODE
    $actual = (($versionLines | ForEach-Object { [string]$_ }) -join "`n").Trim()
  } catch {
    return [pscustomobject]@{ Valid = $false; Path = $exe; Version = ''; Reason = 'version_execution_failed' }
  }
  if ($exit -ne 0 -or $actual -ne $ExpectedVersion) {
    return [pscustomobject]@{ Valid = $false; Path = $exe; Version = $actual; Reason = 'version_mismatch' }
  }
  return [pscustomobject]@{ Valid = $true; Path = [IO.Path]::GetFullPath($exe); Version = $actual; Reason = '' }
}

function Assert-Manifest {
  param($Manifest)
  $required = @('schema_version','toolkit_version','tool_version','platform','release_tag','asset_name','checksum_asset_name','asset_url','checksum_url','archive_root')
  foreach ($name in $required) {
    if (-not ($Manifest.PSObject.Properties.Name -contains $name) -or [string]::IsNullOrWhiteSpace([string]$Manifest.$name)) {
      throw "Runtime manifest is missing $name."
    }
  }
  if ([int]$Manifest.schema_version -ne 1) { throw 'Unsupported runtime manifest schema.' }
  if ([string]$Manifest.platform -ne 'win-x64') { throw 'This Skill only supports the win-x64 runtime.' }
  if ([string]$Manifest.release_tag -ne ('v' + [string]$Manifest.tool_version)) { throw 'release_tag must exactly match tool_version.' }
  if ([string]$Manifest.toolkit_version -ne [string]$Manifest.tool_version) { throw 'toolkit_version must exactly match tool_version.' }
  if ([string]$Manifest.asset_name -ne ("mo2-mod-installer-v{0}-win-x64.zip" -f [string]$Manifest.tool_version)) { throw 'Unexpected runtime asset name.' }
  if ([string]$Manifest.checksum_asset_name -ne ([string]$Manifest.asset_name + '.sha256')) { throw 'Unexpected checksum asset name.' }
  if ([string]$Manifest.archive_root -ne 'mo2-mod-installer') { throw 'Unexpected runtime archive root.' }
  foreach ($urlName in @('asset_url','checksum_url')) {
    $uri = $null
    if (-not [Uri]::TryCreate([string]$Manifest.$urlName, [UriKind]::Absolute, [ref]$uri)) { throw "Invalid $urlName." }
    if (-not $AllowInsecureTestUrls -and $uri.Scheme -ne 'https') { throw "$urlName must use HTTPS." }
  }
  if (-not ([string]$Manifest.asset_url).EndsWith('/' + [string]$Manifest.release_tag + '/' + [string]$Manifest.asset_name, [StringComparison]::Ordinal)) { throw 'asset_url is not pinned to the declared tag and asset.' }
  if (-not ([string]$Manifest.checksum_url).EndsWith('/' + [string]$Manifest.release_tag + '/' + [string]$Manifest.checksum_asset_name, [StringComparison]::Ordinal)) { throw 'checksum_url is not pinned to the declared tag and asset.' }
}

function Assert-WindowsX64 {
  if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) { throw 'MO2 Agent Toolkit requires 64-bit Windows.' }
  $architecture = $null
  try { $architecture = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString() } catch {}
  if ($architecture) {
    if ($architecture -ne 'X64') { throw "Unsupported Windows architecture: $architecture" }
  } elseif ($env:PROCESSOR_ARCHITECTURE -and $env:PROCESSOR_ARCHITECTURE -notmatch 'AMD64') {
    throw "Unsupported Windows architecture: $env:PROCESSOR_ARCHITECTURE"
  }
}

function Get-ExpectedChecksum {
  param([string]$ChecksumPath, [string]$AssetName)
  $text = [IO.File]::ReadAllText($ChecksumPath, [Text.Encoding]::ASCII).Trim()
  $match = [regex]::Match($text, '^(?<hash>[A-Fa-f0-9]{64})(?:\s+\*?(?<name>[^\r\n]+))?$')
  if (-not $match.Success) { throw 'Checksum asset must contain one SHA-256 line.' }
  $listedName = $match.Groups['name'].Value.Trim()
  if ($listedName -and $listedName -ne $AssetName) { throw 'Checksum filename does not match the runtime asset.' }
  return $match.Groups['hash'].Value.ToUpperInvariant()
}

function Get-FileSha256 {
  param([string]$Path)
  $stream = [IO.File]::OpenRead($Path)
  $sha256 = [Security.Cryptography.SHA256]::Create()
  try {
    return ([BitConverter]::ToString($sha256.ComputeHash($stream))).Replace('-', '')
  } finally {
    $sha256.Dispose()
    $stream.Dispose()
  }
}

function Expand-VerifiedArchive {
  param([string]$ZipPath, [string]$Destination)
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $destinationFull = [IO.Path]::GetFullPath($Destination).TrimEnd('\', '/')
  $archive = [IO.Compression.ZipFile]::OpenRead($ZipPath)
  try {
    foreach ($entry in $archive.Entries) {
      $target = [IO.Path]::GetFullPath((Join-Path $destinationFull $entry.FullName))
      if ($target -ne $destinationFull -and -not $target.StartsWith($destinationFull + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Runtime archive contains an unsafe path: $($entry.FullName)"
      }
    }
  } finally {
    $archive.Dispose()
  }
  [IO.Compression.ZipFile]::ExtractToDirectory($ZipPath, $destinationFull)
}

try {
  $skillRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
  if (-not $ManifestPath) { $ManifestPath = Join-Path $skillRoot 'runtime-manifest.json' }
  if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) { Stop-Bootstrap 2 "Runtime manifest not found: $ManifestPath" }
  try {
    $manifest = [IO.File]::ReadAllText((Resolve-Path -LiteralPath $ManifestPath).Path, [Text.UTF8Encoding]::new($false)) | ConvertFrom-Json
    Assert-Manifest $manifest
    Assert-WindowsX64
  } catch {
    Stop-Bootstrap 2 $_.Exception.Message
  }

  $expectedVersion = [string]$manifest.tool_version
  if (-not $env:LOCALAPPDATA -and -not $CacheRoot) { Stop-Bootstrap 2 'LOCALAPPDATA is unavailable; a runtime cache cannot be selected.' $expectedVersion }
  if (-not $CacheRoot) { $CacheRoot = Join-Path $env:LOCALAPPDATA 'MO2AgentToolkit\runtimes' }
  $CacheRoot = [IO.Path]::GetFullPath($CacheRoot)
  if (-not $LegacyBundlePath) { $LegacyBundlePath = Join-Path $env:LOCALAPPDATA 'MO2AgentToolkit\skill-bundles\mo2-mod-installer' }

  $bundled = Test-ExpectedRuntime $skillRoot $expectedVersion
  if ($bundled.Valid) { Write-Outcome 'ready' 0 $expectedVersion $bundled.Path $false 'bundled' }
  if ($bundled.Reason -notin @('directory_missing','executable_missing')) { $script:Warnings.Add("Bundled runtime was ignored: $($bundled.Reason).") }

  $versionRoot = Join-Path $CacheRoot $expectedVersion
  $targetRoot = Join-Path $versionRoot 'mo2-mod-installer'
  if (-not (Test-ChildPath $targetRoot $CacheRoot)) { Stop-Bootstrap 2 'Computed runtime path escaped the cache root.' $expectedVersion }

  $cached = Test-ExpectedRuntime $targetRoot $expectedVersion
  if ($cached.Valid) { Write-Outcome 'ready' 0 $expectedVersion $cached.Path $false 'versioned' }
  if ($cached.Reason -notin @('directory_missing','executable_missing')) { $script:Warnings.Add("Cached runtime requires repair: $($cached.Reason).") }

  $legacy = Test-ExpectedRuntime $LegacyBundlePath $expectedVersion
  if ($legacy.Valid) {
    $script:Warnings.Add('Using a matching legacy shared Skill Bundle; it can be replaced by the versioned cache on a future cold start.')
    Write-Outcome 'ready' 0 $expectedVersion $legacy.Path $false 'legacy'
  }

  New-Item -ItemType Directory -Path $versionRoot -Force | Out-Null
  $mutexVersion = [regex]::Replace($expectedVersion, '[^A-Za-z0-9_.-]', '_')
  $script:Mutex = New-Object Threading.Mutex($false, "Local\MO2AgentToolkit-runtime-$mutexVersion-win-x64")
  try {
    $script:MutexHeld = $script:Mutex.WaitOne([TimeSpan]::FromMinutes(10))
  } catch [Threading.AbandonedMutexException] {
    $script:MutexHeld = $true
    $script:Warnings.Add('Recovered an abandoned runtime download lock.')
  }
  if (-not $script:MutexHeld) { Stop-Bootstrap 5 'Timed out waiting for another runtime bootstrap process.' $expectedVersion }

  foreach ($staleStage in @(Get-ChildItem -LiteralPath $versionRoot -Directory -Filter '.stage-*' -ErrorAction SilentlyContinue)) {
    if (Test-ChildPath $staleStage.FullName $versionRoot) {
      Remove-Item -LiteralPath $staleStage.FullName -Recurse -Force -ErrorAction SilentlyContinue
    }
  }

  $cached = Test-ExpectedRuntime $targetRoot $expectedVersion
  if ($cached.Valid) { Write-Outcome 'ready' 0 $expectedVersion $cached.Path $false 'versioned' }

  $script:StagePath = Join-Path $versionRoot ('.stage-' + [guid]::NewGuid().ToString('N'))
  $downloadRoot = Join-Path $script:StagePath 'download'
  $extractRoot = Join-Path $script:StagePath 'extract'
  New-Item -ItemType Directory -Path $downloadRoot,$extractRoot -Force | Out-Null
  $zipPath = Join-Path $downloadRoot ([string]$manifest.asset_name)
  $checksumPath = Join-Path $downloadRoot ([string]$manifest.checksum_asset_name)

  try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri ([string]$manifest.checksum_url) -OutFile $checksumPath
    Invoke-WebRequest -UseBasicParsing -Uri ([string]$manifest.asset_url) -OutFile $zipPath
  } catch {
    Stop-Bootstrap 4 ("Failed to download the pinned runtime: " + $_.Exception.Message) $expectedVersion
  }

  try {
    $expectedHash = Get-ExpectedChecksum $checksumPath ([string]$manifest.asset_name)
    $actualHash = Get-FileSha256 $zipPath
    if ($actualHash -ne $expectedHash) { Stop-Bootstrap 3 'Runtime SHA-256 verification failed; the downloaded archive was not installed.' $expectedVersion }
  } catch {
    Stop-Bootstrap 3 $_.Exception.Message $expectedVersion
  }

  try {
    Expand-VerifiedArchive $zipPath $extractRoot
  } catch {
    Stop-Bootstrap 5 ("Runtime extraction failed: " + $_.Exception.Message) $expectedVersion
  }

  $candidateRoot = Join-Path $extractRoot ([string]$manifest.archive_root)
  $candidate = Test-ExpectedRuntime $candidateRoot $expectedVersion
  if (-not $candidate.Valid) { Stop-Bootstrap 3 ("Downloaded runtime failed layout/version validation: " + $candidate.Reason) $expectedVersion }

  $quarantine = $null
  try {
    if (Test-Path -LiteralPath $targetRoot) {
      $quarantine = Join-Path $versionRoot ('.invalid-' + (Get-Date -Format 'yyyyMMddHHmmssfff') + '-' + [guid]::NewGuid().ToString('N'))
      Move-Item -LiteralPath $targetRoot -Destination $quarantine
    }
    try {
      Move-Item -LiteralPath $candidateRoot -Destination $targetRoot
    } catch {
      if ($quarantine -and (Test-Path -LiteralPath $quarantine) -and -not (Test-Path -LiteralPath $targetRoot)) {
        Move-Item -LiteralPath $quarantine -Destination $targetRoot
      }
      throw
    }
  } catch {
    Stop-Bootstrap 5 ("Runtime cache promotion failed: " + $_.Exception.Message) $expectedVersion
  }

  $installed = Test-ExpectedRuntime $targetRoot $expectedVersion
  if (-not $installed.Valid) { Stop-Bootstrap 3 'Promoted runtime did not pass final version validation.' $expectedVersion }
  if ($quarantine) { $script:Warnings.Add("A damaged previous cache was quarantined at $quarantine") }
  Write-Outcome 'ready' 0 $expectedVersion $installed.Path $true 'downloaded'
} catch {
  Stop-Bootstrap 5 ("Unexpected bootstrap failure: " + $_.Exception.Message)
} finally {
  if ($script:StagePath -and (Test-Path -LiteralPath $script:StagePath)) {
    Remove-Item -LiteralPath $script:StagePath -Recurse -Force -ErrorAction SilentlyContinue
  }
  if ($script:MutexHeld -and $script:Mutex) {
    try { $script:Mutex.ReleaseMutex() } catch {}
  }
  if ($script:Mutex) { $script:Mutex.Dispose() }
}
