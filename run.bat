@echo off
cd /d "%~dp0"
python app\run.py --open %*
if errorlevel 1 pause
