$taskSince=(Get-Date).AddDays(-2)
$taskErrors=@()
$taskDumps=@()
try {
    $taskDumps=@(Get-ChildItem -LiteralPath 'C:\Windows\LiveKernelReports' -Recurse -File -Filter '*.dmp' -ErrorAction Stop |
        Where-Object {$_.LastWriteTime -ge $taskSince} |
        Select-Object FullName,Length,LastWriteTime)
} catch {$taskErrors+=('LiveKernelReports: '+$_.Exception.Message)}
$taskEvents=@()
foreach($taskLog in @('System','Application')) {
    try {
        $taskEvents+=@(Get-WinEvent -FilterHashtable @{LogName=$taskLog;StartTime=$taskSince} -ErrorAction Stop |
            Where-Object {$_.ProviderName -match 'Display|AMD|WHEA|Windows Error Reporting' -and $_.Message -match 'LiveKernelEvent|GPU|strata|AMD|parity|parit'} |
            Select-Object -First 20 TimeCreated,Id,ProviderName,Message)
    } catch {$taskErrors+=($taskLog+': '+$_.Exception.Message)}
}
$taskReport=[ordered]@{scope='Read-only Windows postmortem inventory; no GPU workload, no driver or clock changes';since=$taskSince;dumps=$taskDumps;events=$taskEvents;read_errors=$taskErrors;root_cause_confirmed=$false}
$taskReport | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath 'output/verification/gpu-postmortem-inventory.json' -Encoding UTF8
[pscustomobject]@{Dumps=$taskDumps.Count;Events=$taskEvents.Count;ReadErrors=$taskErrors.Count;RootCauseConfirmed=$false}
