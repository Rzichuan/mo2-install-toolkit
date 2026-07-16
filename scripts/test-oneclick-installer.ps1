$ErrorActionPreference='Stop'
$Root=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Manifest=Get-Content -LiteralPath (Join-Path $Root 'skills\mo2-mod-installer\runtime-manifest.json') -Encoding UTF8 -Raw|ConvertFrom-Json
$Version=[string]$Manifest.tool_version
$Base=Join-Path $env:TEMP ('mo2-oneclick-test-'+[guid]::NewGuid().ToString('N'))
$TestHome=Join-Path $Base 'home';$TestLocal=Join-Path $Base 'local'
try{
  New-Item -ItemType Directory -Path $TestHome,$TestLocal -Force|Out-Null
  $DetectionFailed=$false
  try{& (Join-Path $Root 'install.ps1') -Version $Version -Target Auto -AgentHome $TestHome -LocalAppDataRoot $TestLocal -AssetDirectory (Join-Path $Root 'release')|Out-Null}catch{$DetectionFailed=$true}
  if(-not $DetectionFailed){throw 'Auto installation accepted a home with neither client.'}
  foreach($Agent in @('.codex','.claude')){$Old=Join-Path $TestHome "$Agent\skills\mo2-mod-installer";New-Item -ItemType Directory -Path $Old -Force|Out-Null;Set-Content -LiteralPath (Join-Path $Old 'old-marker.txt') -Value $Agent -Encoding UTF8}
  & (Join-Path $Root 'install.ps1') -Version $Version -Target Auto -AgentHome $TestHome -LocalAppDataRoot $TestLocal -AssetDirectory (Join-Path $Root 'release')|Out-Null
  & (Join-Path $Root 'install.ps1') -Version $Version -Target Codex -AgentHome $TestHome -LocalAppDataRoot $TestLocal -AssetDirectory (Join-Path $Root 'release')|Out-Null
  foreach($Agent in @('.codex','.claude')){$Link=Join-Path $TestHome "$Agent\skills\mo2-mod-installer";$Item=Get-Item -LiteralPath $Link -Force;if($Item.LinkType -ne 'Junction'){throw "Expected Junction: $Link"}}
  $Data=Get-Content -LiteralPath (Join-Path $TestLocal 'MO2AgentToolkit\adapter-install.json') -Encoding UTF8 -Raw|ConvertFrom-Json
  if(@($Data.adapters).Count -ne 2){throw 'Targeted reinstall lost an existing managed adapter.'}
  $Markers=@(Get-ChildItem -LiteralPath (Join-Path $TestLocal 'MO2AgentToolkit\adapter-backups') -Filter old-marker.txt -File -Recurse);if($Markers.Count -ne 2){throw 'Existing user Skills were not backed up.'}
  $Actual=((& (Join-Path ([string]$Data.runtime) 'bin\mo2-tool.exe') --version)|Out-String).Trim();if($Actual -ne $Version){throw "Installed runtime mismatch: $Actual"}
  & (Join-Path $Root 'uninstall.ps1') -LocalAppDataRoot $TestLocal -RemoveRuntime|Out-Null
  if(Test-Path -LiteralPath (Join-Path $TestHome '.codex\skills\mo2-mod-installer')){throw 'Adapter remains after uninstall.'}
  Write-Output "One-command installer integration test passed for $Version."
}finally{
  $Temp=[IO.Path]::GetFullPath($env:TEMP).TrimEnd('\');$Full=[IO.Path]::GetFullPath($Base)
  if($Full.StartsWith($Temp+'\',[StringComparison]::OrdinalIgnoreCase)-and(Test-Path -LiteralPath $Full)){Remove-Item -LiteralPath $Full -Recurse -Force}
}
