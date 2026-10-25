<#
.SYNOPSIS
  Resolves the Python interpreter that can actually run the dashboard on this PC.
.DESCRIPTION
  Every launcher used to hardcode .venv/Scripts/python.exe. That environment keeps the
  web server dependencies but has no torch, transformers, trl, diffusers, peft or datasets,
  so a dashboard started from it cannot train, run Safetensors inference or generate media.

  This helper prints one interpreter path and nothing else, so the .bat files and the
  PowerShell launchers can pipe it straight into Start-Process.

  Resolution order:
    1. data/dashboard-python-selection.json "active", when it still has the ML stack.
    2. Isolated candidates under output/updates/python-plans, newest first.
    3. The system Python installations found on this machine.
    4. .venv/Scripts/python.exe as the last resort.
.EXAMPLE
  powershell -File tools\Risolvi-Python-Dashboard.ps1
#>
param([switch]$Quiet)
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$required=@('torch','transformers','imageio_ffmpeg','psutil')

function Test-Interpreter($path){
  if(-not $path){return $false}
  $full=[IO.Path]::GetFullPath($path)
  if(-not (Test-Path -LiteralPath $full)){return $false}
  # A Python literal, not a PowerShell array: this text is executed by Python itself.
  $modules = ($required | ForEach-Object { "'$_'" }) -join ','
  $code = "import sys`nimport importlib.util as u`nmissing=[m for m in [$modules] if u.find_spec(m) is None]`nsys.exit(1 if missing else 0)"
  try{
    & $full -I -c $code *> $null
    return $LASTEXITCODE -eq 0
  }catch{ return $false }
}

$candidates=@()
$selection=Join-Path $root 'data/dashboard-python-selection.json'
if(Test-Path -LiteralPath $selection){
  try{
    $saved=Get-Content -LiteralPath $selection -Raw|ConvertFrom-Json
    if($saved.active){$candidates+=$saved.active}
  }catch{}
}
if(Test-Path -LiteralPath (Join-Path $root 'output/updates/python-plans')){
  Get-ChildItem -LiteralPath (Join-Path $root 'output/updates/python-plans') -Directory -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    ForEach-Object { $candidates += (Join-Path $_.FullName 'environment/Scripts/python.exe') }
}
foreach($name in @('python.exe','python3.exe')){
  $found=Get-Command $name -ErrorAction SilentlyContinue
  if($found){$candidates+=$found.Source}
}
foreach($dir in @("$env:LOCALAPPDATA\Programs\Python",'C:\Python313','C:\Python312','C:\Python311','C:\Python310')){
  if(Test-Path -LiteralPath $dir){
    Get-ChildItem -LiteralPath $dir -Directory -ErrorAction SilentlyContinue |
      ForEach-Object { $candidates += (Join-Path $_.FullName 'python.exe') }
  }
}
$candidates += (Join-Path $root '.venv/Scripts/python.exe')

$resolved=$null
foreach($candidate in $candidates){
  if(Test-Interpreter $candidate){$resolved=[IO.Path]::GetFullPath($candidate);break}
}
if(-not $resolved){
  $fallback=[IO.Path]::GetFullPath((Join-Path $root '.venv/Scripts/python.exe'))
  if(-not $Quiet){
    Write-Warning 'No interpreter with the full ML stack was found; using .venv. Training, Safetensors inference and media generation will be unavailable.'
  }
  $resolved=$fallback
}
Write-Output $resolved
