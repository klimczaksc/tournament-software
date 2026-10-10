@echo off
setlocal
cd /d %~dp0

echo ======================================
echo Tournament Software launcher

echo ======================================

echo Checking Python...
where py >nul 2>nul
if %errorlevel%==0 (
    set PY_CMD=py
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set PY_CMD=python
    ) else (
        echo Python is not installed or not added to PATH.
        echo Install Python 3.11+ and run this file again.
        pause
        exit /b 1
    )
)

echo Installing required packages...
%PY_CMD% -m pip install --upgrade pip
%PY_CMD% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Package installation failed.
    pause
    exit /b 1
)

echo Starting application...
start "" http://127.0.0.1:5069
%PY_CMD% app.py

pause
