@echo off
setlocal EnableExtensions

cd /d "%~dp0" || (
    echo Failed to enter application folder.
    pause
    exit /b 1
)

if not exist "logs" mkdir "logs"
set "START_LOG_FILE=%CD%\logs\start.log"
set "APP_LOG_FILE=%CD%\logs\app.log"

echo.>> "%START_LOG_FILE%"
echo [%date% %time%] start.bat started >> "%START_LOG_FILE%"

call :find_python
if errorlevel 1 (
    echo Python was not found. Please install Python 3.10 or newer and add it to PATH.
    echo [%date% %time%] Python was not found. >> "%START_LOG_FILE%"
    pause
    exit /b 1
)

if /I "%~1"=="--check" (
    echo start.bat check OK.
    echo Application folder: %CD%
    echo Start log file: %START_LOG_FILE%
    echo App log file: %APP_LOG_FILE%
    echo Python command: %PYTHON_CMD%
    exit /b 0
)

%PYTHON_CMD% -c "import PySide6, pyqtgraph, pandas, numpy, requests" >> "%START_LOG_FILE%" 2>&1
if errorlevel 1 (
    echo Installing Python dependencies. This may take a few minutes...
    %PYTHON_CMD% -m pip install -r requirements.txt >> "%START_LOG_FILE%" 2>&1
    if errorlevel 1 (
        echo Dependency installation failed.
        echo See log: %START_LOG_FILE%
        pause
        exit /b 1
    )
)

%PYTHON_CMD% main_app.py
if errorlevel 1 (
    echo Application failed to start.
    echo See app log: %APP_LOG_FILE%
    echo See start log: %START_LOG_FILE%
    pause
    exit /b 1
)

endlocal
exit /b 0

:find_python
where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
    exit /b 0
)

where python >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=python"
    exit /b 0
)

exit /b 1
