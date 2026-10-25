$ErrorActionPreference = 'Stop'
# Documented Anthropic third-party desktop user policy. Never change machine policy.
$projectRoot = Split-Path $PSScriptRoot -Parent
$artifactDir = Join-Path $projectRoot 'output/tools/claude-desktop'
New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null
$machinePolicy = Get-Item 'HKLM:\SOFTWARE\Policies\Claude' -ErrorAction SilentlyContinue
if ($machinePolicy) {
    foreach ($policyName in $machinePolicy.GetValueNames()) {
        if ($machinePolicy.GetValueKind($policyName) -in @('String','ExpandString','DWord')) {
            throw 'Existing Claude machine policy takes precedence; no settings changed.'
        }
    }
}
$policyPath = 'HKCU:\SOFTWARE\Policies\Claude'
$existingPolicy = Get-Item $policyPath -ErrorAction SilentlyContinue
$backupPath = Join-Path $artifactDir ('policy-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.json')
$backup = @{}
if ($existingPolicy) {
    foreach ($policyName in $existingPolicy.GetValueNames()) {
        $backup[$policyName] = @{value=$existingPolicy.GetValue($policyName);kind=[string]$existingPolicy.GetValueKind($policyName)}
    }
    # Do not replace a pre-existing user's configuration implicitly.
    if ($backup.Count) { throw 'Existing Claude user policy found; no settings changed.' }
}
@{existed=[bool]$existingPolicy;values=$backup} | ConvertTo-Json -Depth 8 | Set-Content $backupPath -Encoding utf8
$gatewayPolicy = @{
    inferenceProvider='gateway'
    inferenceGatewayBaseUrl='http://127.0.0.1:8090'
    inferenceGatewayApiKey='none'
    inferenceGatewayAuthScheme='bearer'
    inferenceCredentialKind='static'
    deploymentOrganizationUuid='a301dc19-30be-4f65-ad1c-2700e851a865'
}
New-Item -Path $policyPath -Force | Out-Null
foreach ($entry in $gatewayPolicy.GetEnumerator()) {
    New-ItemProperty -Path $policyPath -Name $entry.Key -Value $entry.Value -PropertyType String -Force | Out-Null
}
# No inferenceModels override: /v1/models dynamically discovers Strata's backend/model.
$rollback = @'
$ErrorActionPreference='Stop'
Remove-ItemProperty -Path 'HKCU:\SOFTWARE\Policies\Claude' -Name 'inferenceProvider','inferenceGatewayBaseUrl','inferenceGatewayApiKey','inferenceGatewayAuthScheme','inferenceCredentialKind','deploymentOrganizationUuid' -ErrorAction SilentlyContinue
'@
$rollback | Set-Content (Join-Path $artifactDir 'rollback-policy.ps1') -Encoding utf8
Write-Output 'Official Claude Desktop user gateway policy configured; backup and rollback saved.'
