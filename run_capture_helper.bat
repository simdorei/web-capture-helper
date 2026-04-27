@echo off
setlocal
cd /d %~dp0
if not exist .venv\Scripts\activate.bat (
  echo .venv not found. Run setup_windows.bat first.
  exit /b 1
)
call .venv\Scripts\activate.bat
set PYTHONPATH=src
python -m web_capture_helper.main
