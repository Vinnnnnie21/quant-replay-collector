@echo off
REM Tight feedback loop for pytest issue
cd /d %~dp0

echo ========================================
echo Phase 2: Local reproduction attempt
echo ========================================

set QT_QPA_PLATFORM=offscreen

echo.
echo [Test 1] Can pytest collect tests?
.\.venv\Scripts\python.exe -m pytest --collect-only -q
if errorlevel 1 (
    echo FAILED: pytest collection failed
    pause
    exit /b 1
)
echo PASSED: Test collection works

echo.
echo [Test 2] Can we run one simple test?
.\.venv\Scripts\python.exe -m pytest tests/test_import_smoke.py -v
if errorlevel 1 (
    echo FAILED: Simple test failed
    pause
    exit /b 1
)
echo PASSED: Simple test works

echo.
echo [Test 3] Run all tests with verbose output
.\.venv\Scripts\python.exe -m pytest -v --tb=short --maxfail=1
if errorlevel 1 (
    echo FAILED: Full test suite failed
    echo Check output above for the specific failing test
    pause
    exit /b 1
)

echo.
echo ========================================
echo All tests passed locally!
echo ========================================
pause
