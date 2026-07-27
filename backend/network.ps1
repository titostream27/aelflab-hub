$if = Get-NetAdapter | Where-Object { $_.Status -eq 'Up' -and $_.InterfaceDescription -notlike '*Virtual*' -and $_.InterfaceDescription -notlike '*VMware*' -and $_.InterfaceDescription -notlike '*Tailscale*' } | Select-Object -First 1
if ($if) {
    $s = Get-NetAdapterStatistics -Name $if.Name -ErrorAction SilentlyContinue
    if ($s) {
        Write-Host ('{0}|{1}|{2}' -f $if.Name, $s.ReceivedBytes, $s.SentBytes)
    }
}
