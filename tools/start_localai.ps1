param([int]$Port=8090,[switch]$Open)
$ErrorActionPreference='Stop'
function Test-LocalAiPortAvailable {
    param([ValidateRange(1,65535)][int]$Port)
    $probe=[System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any,$Port)
    $probe.Server.ExclusiveAddressUse=$true
    try {
        $probe.Start()
        return $true
    } catch [System.Net.Sockets.SocketException] {
        # An occupied or inaccessible port must never trigger another launch.
        return $false
    } finally {
        $probe.Stop()
    }
}
$projectRoot=Split-Path $PSScriptRoot -Parent
function Open-LocalAiWorkspace {
    param([int]$WorkspacePort)
    Start-Process "http://127.0.0.1:$WorkspacePort/"
}
$base="http://127.0.0.1:$Port"
try{
    $existing=Invoke-RestMethod "$base/health" -TimeoutSec 2
    if($existing.service -ne 'strata'){throw 'Porta occupata da un altro servizio'}
    if($Open){Open-LocalAiWorkspace -WorkspacePort $Port}
    return
}catch{
    if(-not (Test-LocalAiPortAvailable -Port $Port)){throw 'Porta occupata o non accessibile: nessun processo è stato arrestato'}
}
$configuration=Join-Path $projectRoot 'strata-iq3_s.json'
$record=Join-Path $projectRoot '../Strata-data/ultimo-avvio.json'
if(Test-Path $record){$saved=Get-Content $record -Raw|ConvertFrom-Json;if(Test-Path -LiteralPath $saved.config){$configuration=$saved.config}}
# Resolve at start: .venv alone has no torch, transformers, trl or diffusers, so training,
# Safetensors inference and media generation would fail.
$launcher=Join-Path $PSScriptRoot 'Risolvi-Python-Dashboard.ps1'
$python=(& powershell -NoProfile -ExecutionPolicy Bypass -File $launcher).Trim()
if(-not $python){$python=Join-Path $projectRoot '.venv/Scripts/python.exe'}
$env:STRATA_HARNESS_IDLE_STOP='900'
$arguments=@('-X','utf8','serve/server.py','--engine','strata','--config',('"'+$configuration+'"'),'--port',"$Port",'--lazy','--api-monitor','--idle-unload','900','--mcp-config','data/mcp-dashboard.json')
Start-Process $python -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $projectRoot 'output/verification/localai-dashboard.log') -RedirectStandardError (Join-Path $projectRoot 'output/verification/localai-dashboard-errors.log')
for($attempt=0;$attempt -lt 40;$attempt++){
    try{$ready=Invoke-RestMethod "$base/health" -TimeoutSec 2;if($ready.service -eq 'strata'){if($Open){Open-LocalAiWorkspace -WorkspacePort $Port};Write-Output "LocalAI pronta: $base";return}}catch{}
    Start-Sleep -Milliseconds 500
}
throw 'Avvio non completato: controlla il registro localai-dashboard-errors.log'
