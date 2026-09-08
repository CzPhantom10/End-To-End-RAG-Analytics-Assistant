@echo off
REM ---------------------------------------------------------------
REM  Development mode: FastAPI with auto-reload on :8000 and the
REM  Vite dev server with hot module replacement on :5173.
REM  Requires Node.js. Open http://localhost:5173
REM ---------------------------------------------------------------
setlocal
cd /d "%~dp0"

where node >nul 2>nul
if errorlevel 1 (
    echo   [ERROR] Node.js is required for development mode.
    echo   Use run.bat instead - it serves the pre-built client.
    pause
    exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
    echo   [ERROR] Python was not found in the current environment.
    echo   Activate your virtual environment, then run this file again.
    pause
    exit /b 1
)

if not defined VIRTUAL_ENV (
    echo   [ERROR] No virtual environment is active.
    echo   Activate your virtual environment, then run this file again.
    pause
    exit /b 1
)

if not exist "web\node_modules" (
    echo   Installing frontend dependencies...
    pushd web && npm install && popd
)

echo   Starting the API on http://localhost:8000 ...
start "Lumen API" cmd /k python -m server --reload --port 8000

echo   Starting Vite on http://localhost:5173 ...
cd web
npm run dev

endlocal
