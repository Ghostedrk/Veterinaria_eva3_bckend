# Prueba del rate limit de Amazon API Gateway (throttling).
# Envía N solicitudes casi simultáneas y cuenta cuántas responde el backend (200)
# y cuántas rechaza API Gateway por exceso de solicitudes (429 Too Many Requests).
#
# Uso (PowerShell):
#   powershell -ExecutionPolicy Bypass -File deploy\rate-limit-test.ps1 -Url https://<id>.execute-api.us-east-1.amazonaws.com/api/salud/ -Total 30
param(
    [Parameter(Mandatory = $true)][string]$Url,
    [int]$Total = 30
)

Add-Type -AssemblyName System.Net.Http
$client = New-Object System.Net.Http.HttpClient
$client.Timeout = [TimeSpan]::FromSeconds(30)

Write-Host "Enviando $Total solicitudes simultáneas a $Url"
$watch = [System.Diagnostics.Stopwatch]::StartNew()
$tasks = @()
for ($i = 1; $i -le $Total; $i++) { $tasks += $client.GetAsync($Url) }
[System.Threading.Tasks.Task]::WaitAll($tasks)
$watch.Stop()

$codes = $tasks | ForEach-Object { [int]$_.Result.StatusCode }
$i = 0
foreach ($code in $codes) {
    $i++
    $label = if ($code -eq 429) { "429 Too Many Requests (API Gateway)" } else { "$code" }
    Write-Host ("Solicitud {0,2}: {1}" -f $i, $label)
}
Write-Host ""
Write-Host "Resumen en $([math]::Round($watch.Elapsed.TotalSeconds, 2)) s:"
$codes | Group-Object | Sort-Object Name | ForEach-Object { Write-Host ("  HTTP {0}: {1} solicitudes" -f $_.Name, $_.Count) }
$client.Dispose()
