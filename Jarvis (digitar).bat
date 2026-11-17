@echo off
title Jarvis (digitar)
cd /d "%~dp0"
chcp 65001 >nul
".venv\Scripts\python.exe" jarvis.py --texto
pause
