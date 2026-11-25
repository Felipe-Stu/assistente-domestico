# Fecha à força só os processos deste projeto: a janela (electron.exe dentro desta pasta) e o servidor (python com servidor.py).
# Outros programas, inclusive outros Electron e outros Python, não são tocados.
$raiz = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$alvos = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq 'electron.exe' -and $_.ExecutablePath -and $_.ExecutablePath.StartsWith($raiz, [StringComparison]::OrdinalIgnoreCase)) -or
    ($_.Name -like 'python*.exe' -and $_.CommandLine -and $_.CommandLine -like '*app*servidor.py*')
}
if (-not $alvos) { Write-Output 'Nenhum processo do assistente aberto.'; exit 0 }
foreach ($p in $alvos) {
    Write-Output ("Fechando {0} (PID {1})" -f $p.Name, $p.ProcessId)
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
