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
REM    7. Launch uvicorn on http://127.0.0.1:%API_PORT% and the dashboard,
REM       each in its own window
REM    8. Start one autonomous discovery pass (the LLM picks the topics
REM       and the chain runs through to the human gate) and follow it in
REM       this window. AUTO_DISCOVERY=false in .env skips this step;
REM       POST /discovery/run does the same thing by hand.
REM
REM  Requirements: Python on PATH, Postgres 16 installed under the default
REM  ``C:\Program Files\PostgreSQL\16\``, project deps installed
REM  (``pip install -e .`` or the equivalent), corp DB seeded and pgvector
REM  extension created inside it.
REM ─────────────────────────────────────────────────────────────────

cd /d "%~dp0"

REM -- Read DATABASE_URL and DATABASE_URL_SYNC from .env -------------------
set "DATABASE_URL="
set "DATABASE_URL_SYNC="
if exist .env (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
    if /i "%%A"=="DATABASE_URL" set "DATABASE_URL=%%B"
    if /i "%%A"=="DATABASE_URL_SYNC" set "DATABASE_URL_SYNC=%%B"
  )
)
if not defined DATABASE_URL (
  echo [corp] DATABASE_URL is not set in .env. Cannot start without it.
  pause
  exit /b 1
)
if not defined DATABASE_URL_SYNC (
  echo [corp] DATABASE_URL_SYNC is not set in .env. Cannot start without it.
  pause
  exit /b 1
)
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
    echo [corp] Falling back to Postgres on 5432. Update DATABASE_URL in .env if needed.
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

REM -- Pick the API port: API_PORT from .env, else 8010 --------------
REM    Also read API_KEY (sent as X-API-Key when the API requires it) and
REM    AUTO_DISCOVERY (default true).
set "API_PORT=8010"
set "API_KEY="
set "AUTO_DISCOVERY=true"
if exist .env (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
    if /i "%%A"=="API_PORT" set "API_PORT=%%B"
    if /i "%%A"=="API_KEY" set "API_KEY=%%B"
    if /i "%%A"=="AUTO_DISCOVERY" set "AUTO_DISCOVERY=%%B"
  )
)
REM Strip any stray whitespace from the values
for /f "tokens=1" %%A in ("!API_PORT!") do set "API_PORT=%%A"
for /f "tokens=1" %%A in ("!AUTO_DISCOVERY!") do set "AUTO_DISCOVERY=%%A"

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
echo.

REM -- Launch uvicorn in the background so the script can continue ----------
start "CORP API" cmd /k python -m uvicorn corp.api.app:app --host 127.0.0.1 --port !API_PORT!

REM -- Start the React dashboard -------------------------------------------
if exist web\package.json (
  echo [corp] Starting React dashboard on http://localhost:5173 ...
  start "CORP Dashboard" cmd /k "cd /d "%~dp0web" && npm run dev"
)

REM -- Wait a moment for the servers to initialise, then open the browser ---
ping -n 3 127.0.0.1 >nul
echo [corp] Opening browser ...
start "" "http://localhost:5173"

echo.
echo [corp] API:       http://127.0.0.1:!API_PORT!
echo [corp] Dashboard: http://localhost:5173
echo [corp] Close the "CORP API" and "CORP Dashboard" windows to stop.
echo.

REM -- Run the frozen flow: one autonomous discovery pass, followed here --
if /i "!AUTO_DISCOVERY!"=="false" (
  echo [corp] AUTO_DISCOVERY=false: not starting a discovery pass.
) else (
  echo [corp] Starting an autonomous discovery pass ...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_discovery.ps1" -Port !API_PORT! -ApiKey "!API_KEY!"
)
echo.
pause
endlocal
