# GPU Performance Counters
$gpu = Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match 'AMD|Radeon|RX' } | Select-Object -First 1
Write-Host ("=== GPU ===")
Write-Host ("Name: {0}" -f $gpu.Name)
Write-Host ("VRAM: {0} GB" -f [math]::Round($gpu.AdapterRAM / 1GB, 1))
Write-Host ("Driver: {0}" -f $gpu.DriverVersion)

# Try to get GPU perf counters
$perf = Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapterMemory -ErrorAction SilentlyContinue | Where-Object { $_.Name -match $gpu.Name.Substring(0, [Math]::Min(15, $gpu.Name.Length)) }
if ($perf) {
    Write-Host ("Dedicated Used: {0} MB" -f $perf.DedicatedUsage)
    Write-Host ("Shared Used: {0} MB" -f $perf.SharedUsage)
}
# Try engine utilization
$eng = Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine -ErrorAction SilentlyContinue | Where-Object { $_.Name -like '*3D*' -or $_.Name -like '*Compute*' }
if ($eng) {
    Write-Host ("Engine: {0} - {1}%" -f $eng.Name, $eng.UtilizationPercentage)
}
# CPU temp (for reference)
$therm = Get-CimInstance -Namespace "root/wmi" -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction SilentlyContinue
$i = 0
foreach ($t in $therm) {
    $c = [math]::Round(($t.CurrentTemperature / 10) - 273.15, 0)
    Write-Host ("Thermal Zone {0}: {1}°C" -f $i, $c)
    $i++
}
if ($i -eq 0) { Write-Host "Thermal data: No ACPI data" }
