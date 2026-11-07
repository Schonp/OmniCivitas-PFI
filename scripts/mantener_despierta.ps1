# Mientras esta ventana esté abierta, Windows no suspende la PC (la pantalla sí
# puede apagarse). La abre scripts/demo.ps1: la demo remota necesita que la PC
# siga respondiendo aunque nadie la toque. No cambia la configuración de energía:
# al cerrar la ventana, todo vuelve a ser como antes.
Add-Type -Namespace OmniCivitas -Name Energia -MemberDefinition @"
[DllImport("kernel32.dll")]
public static extern uint SetThreadExecutionState(uint esFlags);
"@

$ES_CONTINUOUS = [uint32]"0x80000000"
$ES_SYSTEM_REQUIRED = [uint32]"0x00000001"
[OmniCivitas.Energia]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED) | Out-Null

$host.UI.RawUI.WindowTitle = "Despierta"
Write-Host "La PC no se va a suspender mientras esta pestaña esté abierta." -ForegroundColor Green
Write-Host "(Windows Update puede reiniciarla igual: pausá las actualizaciones el día de la demo.)" -ForegroundColor DarkGray
while ($true) { Start-Sleep -Seconds 3600 }
