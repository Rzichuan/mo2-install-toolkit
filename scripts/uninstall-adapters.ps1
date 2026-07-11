[CmdletBinding(SupportsShouldProcess)] param()
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Manifest = Join-Path $Root '.adapter-install.json'
if (-not (Test-Path -LiteralPath $Manifest)) { Write-Output 'No adapter installation manifest found.'; exit 0 }
$AllowedRoots = @((Join-Path $HOME '.codex\skills'), (Join-Path $HOME '.claude\skills')) | ForEach-Object { [IO.Path]::GetFullPath($_) }
$Data = Get-Content -Raw -LiteralPath $Manifest -Encoding UTF8 | ConvertFrom-Json
foreach ($Path in $Data.paths) {
  $Resolved = [IO.Path]::GetFullPath([string]$Path)
  if (-not ($AllowedRoots | Where-Object { $Resolved.StartsWith($_ + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) })) { throw "Refusing path outside agent skill roots: $Resolved" }
  if ((Test-Path -LiteralPath $Resolved) -and $PSCmdlet.ShouldProcess($Resolved, 'Remove installed adapter')) { Remove-Item -LiteralPath $Resolved -Recurse -Force }
}
if ($PSCmdlet.ShouldProcess($Manifest, 'Remove installation manifest')) { Remove-Item -LiteralPath $Manifest -Force }
