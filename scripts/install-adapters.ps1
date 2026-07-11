[CmdletBinding(SupportsShouldProcess)] param(
  [ValidateSet('Codex','Claude','Both')][string]$Target = 'Both'
)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Records = @()
if ($Target -in @('Codex','Both')) {
  $Dest = Join-Path $HOME '.codex\skills\mo2-mod-installer'
  if ($PSCmdlet.ShouldProcess($Dest, 'Install Codex skill')) { New-Item -ItemType Directory -Force -Path $Dest | Out-Null; Copy-Item -Path (Join-Path $Root 'skills\mo2-mod-installer\*') -Destination $Dest -Recurse -Force }
  $Records += $Dest
}
if ($Target -in @('Claude','Both')) {
  $Dest = Join-Path $HOME '.claude\skills\mo2-mod-installer'
  if ($PSCmdlet.ShouldProcess($Dest, 'Install Claude Code skill')) { New-Item -ItemType Directory -Force -Path $Dest | Out-Null; Copy-Item -Path (Join-Path $Root 'claude\skills\mo2-mod-installer\*') -Destination $Dest -Recurse -Force }
  $Records += $Dest
}
$Manifest = Join-Path $Root '.adapter-install.json'
if ($PSCmdlet.ShouldProcess($Manifest, 'Record adapter destinations')) { @{paths=$Records} | ConvertTo-Json | Set-Content -LiteralPath $Manifest -Encoding UTF8 }
