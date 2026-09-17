@echo off
setlocal ENABLEEXTENSIONS ENABLEDELAYEDEXPANSION

REM ─────────────────────────────────────────────────────────────────
REM  CORP launcher (Windows)
REM
REM  What it does, in order:
REM    1. cd to the folder this .bat lives in (so relative paths work)
REM    2. Set DATABASE_URL / DATABASE_URL_SYNC and FAIR_ENV_FILE for
REM       THIS process only — overrides any stray User-scope env vars
REM    3. Detect which port Postgres is on (5433 preferred, 5432 fallback)
REM    4. Start the Postgres 16 service if it isn't already accepting
REM    5. Apply any pending alembic migrations
REM    6. Read API_PORT from .env (default 8000) and refuse to start if
REM       something is already listening there (e.g. FAIR, or a stale
REM       CORP instance that never shut down)
REM    7. Launch uvicorn on http://127.0.0.1:%API_PORT% (blocks until Ctrl+C)
REM
REM  Requirements: Python on PATH, Postgres 16 installed under the default
REM  ``C:\Program Files\PostgreSQL\16\``, project deps installed
REM  (``pip install -e .`` or the equivalent), corp DB seeded and pgvector
REM  extension created inside it.
REM ─────────────────────────────────────────────────────────────────

cd /d "%~dp0"

set "DATABASE_URL=postgresql+asyncpg://corp:corp@localhost:5433/corp"
set "DATABASE_URL_SYNC=postgresql://corp:corp@localhost:5433/corp"
set "FAIR_ENV_FILE=fair.env"

set "PG_BIN=C:\Program Files\PostgreSQL\16\bin"
set "PG_ISREADY=%PG_BIN%\pg_isready.exe"

if not exist "%PG_ISREADY%" (
  echo [corp] pg_isready not found at "%PG_ISREADY%".
  echo [corp] Edit this .bat and adjust PG_BIN to your Postgres install.
  pause
  exit /b 1
)

echo [corp] Checking Postgres on localhost:5433 ...
"%PG_ISREADY%" -h localhost -p 5433 -q
if errorlevel 1 (
  echo [corp] Nothing on 5433 yet. Trying to start the Windows service ...
  net start postgresql-x64-16 >nul 2>&1
  REM Give the service a moment to accept connections
  ping -n 4 127.0.0.1 >nul
  "%PG_ISREADY%" -h localhost -p 5433 -q
  if errorlevel 1 (
    echo [corp] Postgres is still not accepting on 5433. Trying 5432 as a fallback ...
    "%PG_ISREADY%" -h localhost -p 5432 -q
    if errorlevel 1 (
      echo [corp] Postgres is not accepting on 5432 either. Start it manually and retry.
      pause
      exit /b 1
    )
    echo [corp] Falling back to Postgres on 5432. Overriding DATABASE_URL for this run.
    set "DATABASE_URL=postgresql+asyncpg://corp:corp@localhost:5432/corp"
    set "DATABASE_URL_SYNC=postgresql://corp:corp@localhost:5432/corp"
  )
)
echo [corp] Postgres is up.

echo [corp] Applying database migrations ...
python -m alembic upgrade head
if errorlevel 1 (
  echo [corp] alembic upgrade failed. See the error above.
  pause
  exit /b 1
)

if exist fair.env (
  echo [corp] Using FAIR provider keys from fair.env
) else (
  echo [corp] No fair.env found. FAIR will run with just GEMINI_API_KEY / GROQ_API_KEY from .env.
)

REM -- Pick the API port: API_PORT from .env, else 8000 --------------
set "API_PORT=8000"
if exist .env (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
    if /i "%%A"=="API_PORT" set "API_PORT=%%B"
  )
)
REM Strip any stray whitespace from the value
for /f "tokens=1" %%A in ("!API_PORT!") do set "API_PORT=%%A"

REM -- Refuse to start if the port is already taken -------------------
set "PORT_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:"TCP.*:!API_PORT! .*LISTENING"') do set "PORT_PID=%%P"
if defined PORT_PID (
  echo.
  echo [corp] Port !API_PORT! is already in use by PID !PORT_PID!:
  for /f "tokens=*" %%L in ('powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter 'ProcessId=!PORT_PID!').CommandLine" 2^>nul') do (
    if not "%%L"=="" echo [corp]   %%L
  )
  echo.
  echo [corp] If that is a stale CORP instance, kill it and rerun:
  echo [corp]   taskkill /F /PID !PORT_PID!
  echo [corp] If it is FAIR or another service, set API_PORT in .env to a free port.
  pause
  exit /b 1
)

echo.
echo [corp] Starting API on http://127.0.0.1:!API_PORT!
echo [corp] Ctrl+C to stop.
echo.
python -m uvicorn corp.api.app:app --host 127.0.0.1 --port !API_PORT!

REM Keep the window open after uvicorn exits so any traceback stays visible.
pause
endlocal
