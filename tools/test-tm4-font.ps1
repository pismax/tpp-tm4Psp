<#
.SYNOPSIS
Launch an isolated PPSSPP copy and optionally navigate/verify TM4 scenario text.
.EXAMPLE
.\tools\test-tm4-font.ps1 -Iso 'D:\Games\TM4.translated.iso' -PpssppDir 'D:\Emulators\PPSSPP' -CopySaves -Visible -Navigate -Verify
#>
param(
    [Parameter(Mandatory=$true)][string]$Iso,
    [string]$PpssppDir,
    [string]$LabRoot = (Join-Path $PSScriptRoot '../artifacts/tm4-ppsspp/emulator'),
    [ValidateRange(1,65535)][int]$Port = 20002,
    [string]$Python = 'python',
    [switch]$CopySaves,
    [switch]$Visible,
    [switch]$Navigate,
    [switch]$Verify,
    [ValidateRange(0,120)][int]$BootWait = 15
)
$ErrorActionPreference = 'Stop'
if ($Verify) { $Navigate = $true }
$resolvedLab = [IO.Path]::GetFullPath($LabRoot)
$executable = Join-Path $resolvedLab 'PPSSPPWindows64.exe'
$helper = Join-Path $PSScriptRoot 'tm4-ppsspp.py'
if (-not (Test-Path -LiteralPath $Iso -PathType Leaf)) { throw 'Choose an existing ISO for the font test.' }
$pidFile = Join-Path $resolvedLab 'test.pid'
if (Test-Path -LiteralPath $pidFile) {
    $testProcess = Get-Process -Id ([int](Get-Content -LiteralPath $pidFile)) -ErrorAction SilentlyContinue
    if ($testProcess -and $testProcess.Path -eq $executable) { Stop-Process -Id $testProcess.Id; $testProcess.WaitForExit(5000) | Out-Null }
}
$marker = Join-Path $resolvedLab '.tpp-tm4-lab.json'
if (-not $PpssppDir -and (Test-Path -LiteralPath $marker)) {
    $labInfo = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
    if ($labInfo.port -ne $Port) { $PpssppDir = $labInfo.source }
}
if ($PpssppDir) {
    $setupArgs = @('-B', $helper, '--port', $Port, 'prepare', '--source', $PpssppDir, '--destination', $resolvedLab)
    if ($CopySaves) { $setupArgs += '--copy-saves' }
    & $Python @setupArgs
    if ($LASTEXITCODE -ne 0) { throw 'PPSSPP lab preparation failed.' }
}
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw 'No isolated emulator exists yet. Supply -PpssppDir with the directory containing PPSSPPWindows64.exe.'
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Debugger port $Port is occupied. Choose another -Port, or close the previous lab instance."
}
$arguments = '"' + (Resolve-Path -LiteralPath $Iso).Path + '"'
$style = if ($Visible) { 'Normal' } else { 'Hidden' }
$process = Start-Process -FilePath $executable -WorkingDirectory $resolvedLab -ArgumentList $arguments -WindowStyle $style -PassThru
$process.Id | Set-Content -LiteralPath $pidFile
Write-Output ('Isolated PPSSPP test PID: ' + $process.Id)
if ($Navigate -or $Verify) {
    $ready = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if ($process.HasExited) { throw 'The isolated PPSSPP process exited during startup.' }
        $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($listener) {
            if (@($listener | Where-Object OwningProcess -ne $process.Id).Count) { throw 'The debugger port is owned by a different process.' }
            $ready = $true; break
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw "PPSSPP did not open debugger port $Port. Check the lab's ppsspp.ini." }
    # This build can expose the server while the CPU is still initializing.
    # Apply the boot grace before debugger requests, not after installing a probe.
    if ($BootWait -gt 0) { Start-Sleep -Seconds $BootWait }
    $report = Join-Path (Split-Path $resolvedLab -Parent) 'last-test.json'
    $probeArgs = @('-B', $helper, '--port', $Port, '--output', $report)
    if ($Navigate) {
        $probeArgs += @('navigate', '--boot-wait', 0)
        if ($Verify) { $probeArgs += '--verify' }
    } else { $probeArgs += 'verify' }
    & $Python @probeArgs
    $probeExit = $LASTEXITCODE
    if (Test-Path -LiteralPath $report) {
        $evidence = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
        $evidence | Add-Member -NotePropertyName iso -NotePropertyValue (Resolve-Path -LiteralPath $Iso).Path -Force
        $evidence | Add-Member -NotePropertyName emulator -NotePropertyValue $executable -Force
        $evidence | Add-Member -NotePropertyName port -NotePropertyValue $Port -Force
        $evidence | Add-Member -NotePropertyName testedAtUtc -NotePropertyValue ([DateTime]::UtcNow.ToString('o')) -Force
        if ($probeExit -eq 0) { $evidence | Add-Member -NotePropertyName isoSha256 -NotePropertyValue (Get-FileHash -LiteralPath $Iso -Algorithm SHA256).Hash.ToLowerInvariant() -Force }
        $evidence | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $report -Encoding utf8
    }
    if ($probeExit -ne 0) { throw "PPSSPP test failed. See $report" }
    Write-Output ('Evidence: ' + $report)
}
