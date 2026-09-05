@echo off
chcp 65001 >nul
rem Manual run (local testing)
cd /d "%~dp0.."
python daily_job_digest.py %*
echo.
pause
