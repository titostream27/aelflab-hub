@echo off
echo Copying cloudflared config to SYSTEM profile...
copy /Y "C:\Users\Home\.cloudflared\config.yml" "C:\Windows\System32\config\systemprofile\.cloudflared\config.yml"
echo.
echo Restarting Cloudflared service...
net stop cloudflared
net start cloudflared
echo.
echo Done! aelflab.com -^> hub.aelflab.com
pause
