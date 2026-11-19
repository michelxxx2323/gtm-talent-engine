@echo off
REM Runs the Attio follow-up cadence and appends to the log. Called by the
REM Windows Task Scheduler through run_hidden.vbs (no console window).
cd /d "%~dp0\.."
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
if not exist data\raw mkdir data\raw
echo ===== %date% %time% ===== >> data\raw\followups.log
python engine\attio_followups.py >> data\raw\followups.log 2>&1
