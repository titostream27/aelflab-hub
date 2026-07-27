@echo off
cd /d D:\homelab\hermes-workspace\hub
start "AelfLab Hub" /B /MIN python backend\main.py
timeout /t 5 /nobreak >nul
start "AelfLab Redirect" /B /MIN python redirect.py
