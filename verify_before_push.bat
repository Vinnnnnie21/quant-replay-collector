@echo off
REM Local verification script for the GitHub Actions quality workflow

echo ========================================
echo Testing locally before pushing to GitHub
echo ========================================

cd /d %~dp0

echo.
echo [1/4] Compiling Python modules...
.\.venv\Scripts\python.exe -m compileall -q quant_collector_app tests
if errorlevel 1 (
    echo FAILED: Compilation errors found
    exit /b 1
)
echo PASSED: All modules compile successfully

echo.
echo [2/4] Running pytest...
set QT_QPA_PLATFORM=offscreen
.\.venv\Scripts\python.exe -m pytest -q --tb=short
if errorlevel 1 (
    echo FAILED: Some tests failed
    exit /b 1
)
echo PASSED: All tests passed

echo.
echo [3/4] Running core self check...
.\.venv\Scripts\python.exe -m quant_collector_app.self_check --core
if errorlevel 1 (
    echo FAILED: Self check failed
    exit /b 1
)
echo PASSED: Self check passed

echo.
echo [4/4] Verifying GitHub Actions workflow exists...
if not exist ".github\workflows\ci.yml" (
    echo FAILED: .github\workflows\ci.yml not found
    exit /b 1
)
echo PASSED: GitHub workflow file exists

echo.
echo ========================================
echo All local checks passed!
echo Ready to push to GitHub
echo ========================================
