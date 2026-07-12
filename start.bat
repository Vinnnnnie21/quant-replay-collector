@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" /b ".venv\Scripts\pythonw.exe" "%CD%\run_app.pyw"
    exit /b 0
)
where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" /b pythonw "%CD%\run_app.pyw"
    exit /b 0
)
python run_app.py
