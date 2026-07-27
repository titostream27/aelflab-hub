@echo off
echo === STOP SERVICE (butuh admin) ===
net stop cloudflared 2>nul
echo.
echo === START TUNNEL sebagai user ===
start "Cloudflared Tunnel" "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --config "C:\Users\Home\.cloudflared\config.yml" run
echo.
echo Tunnel started! hub.aelflab.com should work now.
echo.
echo Note: Close this window to stop the tunnel.
pause
