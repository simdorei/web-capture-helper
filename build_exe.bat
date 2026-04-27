@echo off
setlocal
cd /d %~dp0
if not exist .venv\Scripts\activate.bat call setup_windows.bat
call .venv\Scripts\activate.bat
pyinstaller --clean --onefile --name web-capture-helper ^
  --collect-all fastapi ^
  --collect-all starlette ^
  --collect-all pydantic ^
  --collect-all uvicorn ^
  --collect-submodules h11 ^
  --hidden-import h11 ^
  --hidden-import uvicorn.protocols.http.h11_impl ^
  --hidden-import uvicorn.loops.asyncio ^
  src\web_capture_helper\main.py
if errorlevel 1 exit /b 1
copy /Y browser_capture_snippet.js dist\browser_capture_snippet.js >nul
copy /Y README_QUICKSTART.md dist\README_QUICKSTART.md >nul
if not exist dist\docs mkdir dist\docs
copy /Y docs\CAPTURE_PLAN.md dist\docs\CAPTURE_PLAN.md >nul
echo Built dist\web-capture-helper.exe
