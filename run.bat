@echo off
REM ---------------------------------------------------------------
REM  Lumen - RAG Data Analytics Assistant
REM  One-click launcher (Windows)
REM
REM  Node.js is NOT required: the React client is pre-built into
REM  web\dist and served by the Python backend.
REM ---------------------------------------------------------------
setlocal
cd /d "%~dp0"

echo.
echo   Lumen - RAG Data Analytics Assistant
echo   -------------------------------------------
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo   [ERROR] Python was not found in the current environment.
    echo   Activate your virtual environment, then run this file again.
    echo.
    pause
    exit /b 1
)

if not defined VIRTUAL_ENV (
    echo   [ERROR] No virtual environment is active.
    echo   Activate your virtual environment, then run this file again.
    echo.
    pause
    exit /b 1
)

if not exist ".env" (
    echo   No .env file found - creating one from .env.example
    copy ".env.example" ".env" >nul
    echo   Open .env and paste your Groq API key next to GROQ_API_KEY=
    echo   Get a free key at https://console.groq.com/keys
    echo.
)

if not exist "data\superstore.csv" (
    echo   Downloading the example dataset...
    python "data\fetch_data.py"
)

if not exist "web\dist\index.html" (
    echo   [ERROR] The web client is missing from web\dist.
    echo   Rebuild it on a machine with Node.js installed:
    echo       cd web ^&^& npm install ^&^& npm run build
    echo.
    pause
    exit /b 1
)

echo   Starting. Your browser will open at http://localhost:8000
echo   Press Ctrl+C in this window to stop.
echo.
python -m server

pause
endlocal
