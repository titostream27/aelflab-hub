$gpu = Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match 'AMD|Radeon|RX' } | Select-Object -First 1
if ($gpu) {
    Write-Host ("Name: {0}" -f $gpu.Name)
    Write-Host ("RAM: {0} GB" -f [math]::Round($gpu.AdapterRAM / 1GB, 1))
    Write-Host ("Driver: {0}" -f $gpu.DriverVersion)
    Write-Host ("Resolution: {0}x{1}" -f $gpu.CurrentHorizontalResolution, $gpu.CurrentVerticalResolution)
    $pnp = Get-CimInstance Win32_PnPEntity | Where-Object { $_.PNPClass -eq 'Display' -and $_.Name -match 'AMD|Radeon|RX' } | Select-Object -First 1
    if ($pnp) {
        $pnpId = $pnp.PNPDeviceID
        Write-Host ("PNP ID: {0}" -f $pnpId)
    }
} else {
    Write-Host "No AMD GPU found"
}
# Check for LibreHardwareMonitor / OpenHardwareMonitor WMI
$wmi = Get-CimInstance -Namespace "root\LibreHardwareMonitor" -ClassName Sensor -ErrorAction SilentlyContinue
if ($wmi) { Write-Host "LibreHardwareMonitor found" } else { Write-Host "No LibreHardwareMonitor WMI" }
