@echo off
REM Double-click this file to start the Housing Aggregator website.
cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo Virtual environment not found. Run: python -m venv venv
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

echo.
echo ===========================================
echo   Housing Aggregator is starting...
echo   Your browser will open in a few seconds.
echo   Keep this window open while you use the site.
echo   Press CTRL+C in this window to stop it.
echo ===========================================
echo.

REM give the server a few seconds to start before opening the browser
start "" /b cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:5000"

python run.py
pause
