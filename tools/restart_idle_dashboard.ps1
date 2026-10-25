param([string]$CandidatePython='', [switch]$RecoverCompletedUpdate,[int]$Port=8090)
$m=Invoke-RestMethod http://127.0.0.1:$Port/metrics
$b=Invoke-RestMethod http://127.0.0.1:$Port/inference-backends
foreach($agentKind in @('opencode','dsh','trueforge','hermes','claude')){
    $agentState=Invoke-RestMethod "http://127.0.0.1:$Port/harness/$agentKind/status"
    if($agentState.busy -or ($agentState.owned_process -and $null -eq $agentState.activity_known)){throw 'Agente attivo o attività non verificabile: riavvio rifiutato'}
}
if($m.live.state -ne 'unloaded' -or $b.status -ne 'idle' -or (Test-Path data/.gpu-campaign.lock)){throw 'Servizio occupato: non riavviato'}
$audioState=$null
try{$audioState=Invoke-RestMethod http://127.0.0.1:$Port/local-audio}catch{if($_.Exception.Response.StatusCode -ne 404){throw}}
if($audioState -and $audioState.status -ne 'idle'){throw 'Motore audio attivo: scaricalo prima del riavvio'}
$speechState=$null
try{$speechState=Invoke-RestMethod http://127.0.0.1:$Port/local-speech}catch{if($_.Exception.Response.StatusCode -ne 404){throw}}
if($speechState -and $speechState.status -ne 'idle'){throw 'Motore vocale attivo: scaricalo prima del riavvio'}
$separationState=Invoke-RestMethod http://127.0.0.1:$Port/local-separation
foreach($generationPath in @('local-visual','local-generative-audio')){
    try{$generationState=Invoke-RestMethod "http://127.0.0.1:$Port/$generationPath" -TimeoutSec 5;if($generationState.busy){throw 'Generazione locale in corso: non riavviato'}}catch{if($_.Exception.Response.StatusCode -ne 404){throw}}
}
if($separationState.busy -or $separationState.status -eq 'running'){throw 'Separazione audio in corso: non riavviato'}
$exportState=$null
try{$exportState=Invoke-RestMethod http://127.0.0.1:$Port/local-export}catch{if($_.Exception.Response.StatusCode -ne 404){throw}}
if($exportState -and $exportState.status -eq 'running'){throw 'Conversione in corso: non riavviato'}
$updatesState=$null
try{$updatesState=Invoke-RestMethod http://127.0.0.1:$Port/updates -TimeoutSec 3}catch{
    if($RecoverCompletedUpdate -and (Test-Path -LiteralPath data/update-job.json)){
        $journal=Get-Content -LiteralPath data/update-job.json -Raw|ConvertFrom-Json
        if($journal.state -notin @('selected_strata','rolled_back','activated_cpu','validated')){throw 'Journal aggiornamento non terminale: riavvio rifiutato'}
        $updatesState=[pscustomobject]@{download=$journal}
    }elseif($_.Exception.Response.StatusCode -ne 404){throw}
}
if($updatesState -and $updatesState.harness_update.state -eq 'installing'){throw 'Aggiornamento harness in corso: non riavviato'}
if($updatesState -and $updatesState.download.state -in @('downloading','preparing','validating','resolving','installing_candidate','validating_python')){throw 'Download aggiornamento in corso: non riavviato'}
$airllmState=$null
try{$airllmState=Invoke-RestMethod http://127.0.0.1:$Port/airllm -TimeoutSec 5}catch{if($_.Exception.Response.StatusCode -ne 404){throw}}
if($airllmState -and $airllmState.job.state -eq 'preparing'){throw 'Preparazione AirLLM in corso: non riavviato'}
$openWebUIState=$null
try{$openWebUIState=Invoke-RestMethod http://127.0.0.1:$Port/open-webui -TimeoutSec 5}catch{if($_.Exception.Response.StatusCode -ne 404){throw}}
if($openWebUIState -and ($openWebUIState.busy -or $openWebUIState.setup_busy -or $openWebUIState.job.state -eq 'preparing')){throw 'Open WebUI sta elaborando o preparando il runtime: non riavviato'}
$voiceStudioState=$null
try{$voiceStudioState=Invoke-RestMethod http://127.0.0.1:$Port/voicestudio -TimeoutSec 5}catch{if($_.Exception.Response.StatusCode -ne 404){throw}}
if($voiceStudioState -and $voiceStudioState.busy){throw 'Generazione VoiceStudio in corso: non riavviato'}
$configuration=Invoke-RestMethod http://127.0.0.1:$Port/config
$activeConfigPath=if([IO.Path]::IsPathRooted($configuration.config)){[IO.Path]::GetFullPath($configuration.config)}else{[IO.Path]::GetFullPath((Join-Path (Get-Location).Path $configuration.config))}
$quotedConfig='"{0}"' -f $activeConfigPath
$workspaceRoot=[IO.Path]::GetFullPath((Get-Location).Path)+[IO.Path]::DirectorySeparatorChar
if(!$activeConfigPath.StartsWith($workspaceRoot,[StringComparison]::OrdinalIgnoreCase) -or !(Test-Path -LiteralPath $activeConfigPath)){throw 'Configurazione attiva non verificata: non riavviato'}
$listener=Get-NetTCPConnection -LocalPort $Port -State Listen
$process=Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
$normalizedCommand=$process.CommandLine.Replace('\','/')
$expectedServer=[IO.Path]::GetFullPath((Join-Path (Get-Location).Path 'serve/server.py')).Replace('\','/')
$serverWorkingDirectory=& .venv/Scripts/python.exe -c 'import psutil,sys; print(psutil.Process(int(sys.argv[1])).cwd())' $listener.OwningProcess
$exactServer=$normalizedCommand.Contains($expectedServer)
$relativeServer=($normalizedCommand -match 'serve/server\.py') -and ([IO.Path]::GetFullPath($serverWorkingDirectory.Trim()) -eq [IO.Path]::GetFullPath((Get-Location).Path))
if(!$exactServer -and !$relativeServer){throw 'Processo diverso: non riavviato'}
# Resolve at start: .venv alone has no torch, transformers, trl or diffusers.
$resolver=Join-Path $PSScriptRoot 'Risolvi-Python-Dashboard.ps1'
$launchPython=(& powershell -NoProfile -ExecutionPolicy Bypass -File $resolver).Trim()
if(-not $launchPython){$launchPython='.venv/Scripts/python.exe'}
if(!$CandidatePython -and (Test-Path data/dashboard-python-selection.json)){
    $selection=Get-Content data/dashboard-python-selection.json -Raw|ConvertFrom-Json
    if($selection.active){$CandidatePython=$selection.active}
}
if($CandidatePython){
    $candidateFullPath=[IO.Path]::GetFullPath($CandidatePython)
    $candidateRoot=[IO.Path]::GetFullPath((Join-Path (Get-Location).Path 'output/updates/python-plans'))+[IO.Path]::DirectorySeparatorChar
    if(!$candidateFullPath.StartsWith($candidateRoot,[StringComparison]::OrdinalIgnoreCase) -or !(Test-Path -LiteralPath $candidateFullPath)){throw 'Python candidato fuori dal percorso isolato'}
    $planFolder=Split-Path (Split-Path (Split-Path $candidateFullPath -Parent) -Parent) -Parent
    $manifestPath=Join-Path $planFolder 'environment-manifest.json'
    $candidateManifest=Get-Content -LiteralPath $manifestPath -Raw|ConvertFrom-Json
    if($candidateManifest.dependency_health.state -ne 'healthy' -or !$candidateManifest.server_suite.passed -or $candidateManifest.python -ne $candidateFullPath){throw 'Il candidato non ha superato le verifiche'}
    $launchPython=$candidateFullPath
}
Stop-Process -Id $listener.OwningProcess
Start-Process $launchPython -ArgumentList @('-X','utf8','serve/server.py','--engine','strata','--config',$quotedConfig,'--port',"$Port",'--lazy','--api-monitor','--idle-unload','900') -WindowStyle Hidden -WorkingDirectory (Get-Location).Path -RedirectStandardOutput output/verification/dashboard-optional-backends.log -RedirectStandardError output/verification/dashboard-optional-backends-errors.log
for($i=0;$i -lt 30;$i++){try{$ready=Invoke-RestMethod http://127.0.0.1:$Port/health;Write-Output 'Dashboard pronta';break}catch{Start-Sleep -Milliseconds 500}}
