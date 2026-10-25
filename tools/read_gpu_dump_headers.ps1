# Passive local dump inventory/header read. Does not change drivers, clocks or services.
$taskWorkspace=[IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$taskOutput=Join-Path $taskWorkspace 'output/verification/windows-dump-headers-admin.json'
$taskRecords=@();$taskErrors=@()
foreach($taskFolder in @('C:\Windows\Minidump','C:\Windows\LiveKernelReports')) {
    try {
        $taskFiles=@(Get-ChildItem -LiteralPath $taskFolder -Recurse -File -Filter '*.dmp' -ErrorAction Stop | Sort-Object LastWriteTime -Descending | Select-Object -First 10)
        foreach($taskFile in $taskFiles) {
            $taskRecord=[ordered]@{name=$taskFile.Name;directory=$taskFile.DirectoryName;bytes=$taskFile.Length;modified=$taskFile.LastWriteTime;read_state='unavailable';root_cause_confirmed=$false}
            try {
                $taskStream=[IO.File]::Open($taskFile.FullName,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)
                try {$taskBuffer=New-Object byte[] 128;$taskCount=$taskStream.Read($taskBuffer,0,128)} finally {$taskStream.Dispose()}
                $taskRecord.signature=[Text.Encoding]::ASCII.GetString($taskBuffer,0,[Math]::Min(8,$taskCount));$taskRecord.read_state='read'
                if($taskRecord.signature -eq 'PAGEDU64' -and $taskCount -ge 64){$taskRecord.bugcheck_header_hex=('0x{0:x}' -f [BitConverter]::ToUInt32($taskBuffer,56))}
            } catch {$taskRecord.error=$_.Exception.Message}
            $taskRecords+=[pscustomobject]$taskRecord
        }
    } catch {$taskErrors+=($taskFolder+': '+$_.Exception.Message)}
}
[ordered]@{scope='Local read-only dump headers, at most 128 bytes each; no dump upload or GPU workload';records=$taskRecords;errors=$taskErrors} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $taskOutput -Encoding UTF8
