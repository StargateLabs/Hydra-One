$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot -Parent
$debugger=Join-Path $taskRoot 'output/research/windbg/portable/x64/amd64/cdb.exe'
$destination=Join-Path $taskRoot 'output/verification/gpu-dump-analysis'
New-Item -ItemType Directory -Force -Path $destination | Out-Null
$records=@()
foreach($dump in @('C:\Windows\LiveKernelReports\WATCHDOG\WATCHDOG-20261010-1329.dmp','C:\Windows\LiveKernelReports\WATCHDOG\WATCHDOG-20261010-1332.dmp','C:\Windows\Minidump\100826-13078-01.dmp')){
    $name=[IO.Path]::GetFileNameWithoutExtension($dump)
    $log=Join-Path $destination ($name+'.txt')
    try{
        if(!(Test-Path -LiteralPath $dump)){throw 'Dump missing'}
        # Offline symbols only. Dumps remain in their original Windows location.
        $arguments=@('-z',('"'+$dump+'"'),'-y','""','-logo',('"'+$log+'"'),'-c','"!analyze -v; lm; q"')
        $process=Start-Process -FilePath $debugger -ArgumentList $arguments -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $destination ($name+'.stdout.txt')) -RedirectStandardError (Join-Path $destination ($name+'.stderr.txt'))
        $finished=$process.WaitForExit(45000)
        if(!$finished){Stop-Process -Id $process.Id;throw 'Offline analysis timed out after 45 seconds'}
        $records+=@{dump=$dump;exit_code=$process.ExitCode;log=$log;state='analyzed'}
    }catch{$records+=@{dump=$dump;state='failed';error=$_.Exception.Message}}
}
@{scope='Read-only offline Windows dump analysis; no GPU workload, no uploads, no driver changes';records=$records;completed_at=(Get-Date).ToString('o')}|ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $destination 'report.json') -Encoding UTF8
