<#
.SYNOPSIS
  Shows which Strata services are listening, on which port, and with which model.
.DESCRIPTION
  This PC can run two Strata dashboards at the same time, on 8088 and 8090, each with its own
  model selection. This tool prints the live state so a second service is never started on a
  port that is already taken, and so the two dashboards are never mixed up.

  It only reads state. It starts nothing, stops nothing and never touches other programs.
.EXAMPLE
  powershell -File tools\Stato-porte.ps1
#>
param([switch]$Json)
$ErrorActionPreference='Stop'
try{[Console]::OutputEncoding=[Text.Encoding]::UTF8}catch{}
$root=Split-Path $PSScriptRoot -Parent
$known=@(
  @{Port=8090;  Role='Dashboard unica (MCP e agenti)'; Config='strata-hf_85a248b2_q2_0.json'}
  @{Port=18198; Role='Proxy Headroom verso la 8090';  Config=$null}
  @{Port=8088;  Role='non piu usata (rilevata se avviata)'; Config=$null}
  @{Port=8093;  Role='Whisper (trascrizione)';        Config=$null}
  @{Port=8094;  Role='Kokoro / PocketTTS (voce)';     Config=$null}
  @{Port=8091;  Role='Backend opzionale Unsloth';     Config=$null}
)
$rows=@()
foreach($entry in $known){
  $owner=$null
  try{
    $listener=Get-NetTCPConnection -LocalPort $entry.Port -State Listen -ErrorAction SilentlyContinue |
      Sort-Object OwningProcess | Select-Object -First 1
    if($listener){$owner=$listener.OwningProcess}
  }catch{}
  $row=[pscustomobject]@{
    Port=$entry.Port; Role=$entry.Role; State='libera'; Pid=''; Model=''; Context=''
  }
  if($owner){
    $row.State='attiva'; $row.Pid=$owner
    if($entry.Port -eq 18198){
      try{
        $live=Invoke-RestMethod 'http://127.0.0.1:18198/livez' -TimeoutSec 3
        $row.Model=('Headroom '+$live.version+' ('+$live.status+')'); $row.Context='proxy'
      }catch{$row.Model='Headroom'}
    } else {
      try{
        $health=Invoke-RestMethod ("http://127.0.0.1:{0}/health" -f $entry.Port) -TimeoutSec 3
        $row.Model=$health.model; $row.Context=$health.max_context
      }catch{}
    }
  }
  $rows+=$row
}
$other=@()
try{
  Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalAddress -in '127.0.0.1','::1' -and $known.LocalPort -notcontains $_.LocalPort } |
    Group-Object LocalPort |
    ForEach-Object {
      $p=$_.Group[0].OwningProcess
      $name=(Get-Process -Id $p -ErrorAction SilentlyContinue).ProcessName
      if($name -and $name -notmatch 'python'){ $other += [pscustomobject]@{Port=$_.Name; Program=$name; Pid=$p} }
    }
}catch{}
if($Json){
  [pscustomobject]@{strata=$rows;other_programs=$other} | ConvertTo-Json -Depth 4
  return
}
Write-Output ''
Write-Output '  STATO PORTE STRATA'
Write-Output '  ------------------------------------------------------------'
foreach($r in $rows){
  $model=if($r.Model){$r.Model}else{'-'}
  $extra=if($r.Context){(' | ctx '+$r.Context)}else{''}
  Write-Output ('  {0,-6} {1,-9} {2,-32} {3}{4}' -f $r.Port,$r.State,$r.Role,$model,$extra)
}
if($other){
  Write-Output ''
  Write-Output '  Altre porte su 127.0.0.1 (non gestite da Strata):'
  foreach($o in $other){ Write-Output ('    {0,-7} {1}' -f $o.Port,$o.Program) }
}
Write-Output ''
Write-Output '  Apri http://127.0.0.1:8090/ per l unica dashboard.'
Write-Output ''
