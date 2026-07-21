@echo off
setlocal EnableExtensions
set "PYTHONNOUSERSITE=1"

cd /d "%~dp0" || (
    echo Failed to enter application folder.
    pause
    exit /b 1
)

if not exist "logs" mkdir "logs"
set "LOG_FILE=%CD%\logs\build.log"

echo.>> "%LOG_FILE%"
echo [%date% %time%] build_windows.bat started >> "%LOG_FILE%"

call :find_python
if errorlevel 1 (
    echo Python was not found. Please install Python 3.10 or newer and add it to PATH.
    echo [%date% %time%] Python was not found. >> "%LOG_FILE%"
    pause
    exit /b 1
)

%PYTHON_CMD% "%~dp0..\scripts\write_windows_version_info.py" ^
    --version-file "build\qrc-version-info.txt" ^
    --batch-file "build\qrc-release-env.bat" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo Windows release metadata generation failed.
    echo See log: %LOG_FILE%
    pause
    exit /b 1
)
set "PYTHONUSERBASE=%CD%\build\isolated-python-user"
call "build\qrc-release-env.bat"

if /I "%~1"=="--check" (
    echo build_windows.bat check OK.
    echo Application folder: %CD%
    echo Log file: %LOG_FILE%
    echo Python command: %PYTHON_CMD%
    echo Version: %QRC_VERSION%
    echo Windows file version: %QRC_WINDOWS_FILE_VERSION%
    echo Package name: %QRC_PACKAGE_NAME%
    exit /b 0
)

echo Installing and checking dependencies...
%PYTHON_CMD% -m pip install -r ..\requirements-lock.txt >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo Dependency installation failed.
    echo See log: %LOG_FILE%
    pause
    exit /b 1
)

echo Building Windows executable...
set "ICON_ARG="
if exist "assets\app_icon.ico" set "ICON_ARG=--icon=assets\app_icon.ico --add-data=assets\app_icon.ico;assets --add-data=assets\app_logo.png;assets --add-data=assets\app_logo_light.png;assets"
%PYTHON_CMD% -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onedir ^
    --windowed ^
    --name QRC ^
    --version-file=build\qrc-version-info.txt ^
    --exclude-module=pytest ^
    --exclude-module=pyarrow.tests ^
    --exclude-module=sklearn.datasets ^
    --paths "%CD%" ^
    --add-data=translations;translations ^
    %ICON_ARG% main_app.py >> "%LOG_FILE%" 2>&1

if errorlevel 1 (
    echo Build failed.
    echo See log: %LOG_FILE%
    pause
    exit /b 1
)

%PYTHON_CMD% "%~dp0..\scripts\prune_windows_package.py" --root "dist\QRC" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo Build pruning failed.
    echo See log: %LOG_FILE%
    pause
    exit /b 1
)

%PYTHON_CMD% "%~dp0..\scripts\verify_frozen_archive.py" "dist\QRC\QRC.exe" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo Build verification failed: required application modules are missing.
    echo See log: %LOG_FILE%
    pause
    exit /b 1
)

echo.
%PYTHON_CMD% "%~dp0..\scripts\write_release_manifest.py" --root "dist\QRC" --entrypoint "QRC.exe" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo Release manifest generation failed.
    echo See log: %LOG_FILE%
    pause
    exit /b 1
)

echo Build completed: %CD%\dist\QRC\QRC.exe
echo Release package name: %QRC_PACKAGE_NAME%
if not exist "assets\app_icon.ico" echo App icon not found; QRC.exe uses the default executable icon.
echo Build log: %LOG_FILE%
pause
endlocal
exit /b 0

:find_python
if exist "..\.venv\Scripts\python.exe" (
    set "PYTHON_CMD=..\.venv\Scripts\python.exe"
    exit /b 0
)

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
