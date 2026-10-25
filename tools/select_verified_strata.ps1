$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $taskRoot
$originalHash=(Get-FileHash -LiteralPath engine/strata.exe -Algorithm SHA256).Hash
& tools/restart_idle_dashboard.ps1
$before=Invoke-RestMethod http://127.0.0.1:8088/updates
if(!$before.strata_candidate_validation_current){throw 'Candidate is not validated'}
if($before.strata_runtime_selection.active){
    $prior=Invoke-RestMethod http://127.0.0.1:8088/updates/rollback -Method Post -ContentType application/json -Body '{"component":"strata"}'
    & tools/restart_idle_dashboard.ps1
}
$selected=Invoke-RestMethod http://127.0.0.1:8088/updates/activate -Method Post -ContentType application/json -Body '{}'
& tools/restart_idle_dashboard.ps1
$candidate=Invoke-RestMethod http://127.0.0.1:8088/metrics
if($candidate.engine.version -ne '0.1.42'){throw 'New engine version not detected'}
if($candidate.live.state -ne 'unloaded'){throw 'Selection loaded the model unexpectedly'}
$rollback=Invoke-RestMethod http://127.0.0.1:8088/updates/rollback -Method Post -ContentType application/json -Body '{"component":"strata"}'
& tools/restart_idle_dashboard.ps1
$restored=Invoke-RestMethod http://127.0.0.1:8088/metrics
if($restored.engine.version -ne '0.1.40.3'){throw 'Original engine version not restored'}
$selected=Invoke-RestMethod http://127.0.0.1:8088/updates/activate -Method Post -ContentType application/json -Body '{}'
& tools/restart_idle_dashboard.ps1
$final=Invoke-RestMethod http://127.0.0.1:8088/metrics
if($final.engine.version -ne '0.1.42'){throw 'Final selected version mismatch'}
if((Get-FileHash -LiteralPath engine/strata.exe -Algorithm SHA256).Hash -ne $originalHash){throw 'Original engine changed'}
@{passed=$true;selected_version=$final.engine.version;restored_version=$restored.engine.version;final_state=$final.live.state;original_executable_preserved=$true;scope='Actual dashboard native selection, restart, rollback, restart and final selection; model remains unloaded';completed_at=(Get-Date).ToString('o')}|ConvertTo-Json -Depth 5|Set-Content output/verification/strata-update-selection-rollback-real.json -Encoding utf8
