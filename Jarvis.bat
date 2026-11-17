@echo off
title Jarvis
cd /d "%~dp0"
chcp 65001 >nul
".venv\Scripts\python.exe" jarvis.py %*
pause
