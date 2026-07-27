$gpu = Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match 'AMD|Radeon|RX|NVIDIA' } | Select-Object -First 1
Write-Host ("GPU_NAME={0}" -f $gpu.Name)
Write-Host ("GPU_RAM={0}" -f [math]::Round($gpu.AdapterRAM / 1GB, 1))
Write-Host ("GPU_DRIVER={0}" -f $gpu.DriverVersion)

# Try perf counters
try {
    $eng = Get-Counter '\GPU Engine(*)\Utilization Percentage' -ErrorAction SilentlyContinue -SampleInterval 1 -MaxSamples 1
    if ($eng) {
        $val = $eng.CounterSamples | Where-Object { $_.Path -match '3D|Compute' } | Select-Object -First 1
        if ($val) { Write-Host ("GPU_UTIL={0}" -f [math]::Round($val.CookedValue, 0)) }
    }
} catch { }
# VRAM usage via perfmon
try {
    $mem = Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage' -ErrorAction SilentlyContinue -SampleInterval 1 -MaxSamples 1
    if ($mem) {
        $v = $mem.CounterSamples | Select-Object -First 1
        if ($v) { Write-Host ("GPU_VRAM_USED={0}" -f [math]::Round($v.CookedValue / 1MB, 0)) }
    }
} catch { }
# Temperature from perfmon
try {
    $temp = Get-Counter '\GPU(*)\Current Temperature' -ErrorAction SilentlyContinue -SampleInterval 1 -MaxSamples 1
    if ($temp) {
        $t = $temp.CounterSamples | Select-Object -First 1
        if ($t) { Write-Host ("GPU_TEMP={0}°C" -f [math]::Round($t.CookedValue, 0)) }
    }
} catch { Write-Host "TEMP_NA" }
