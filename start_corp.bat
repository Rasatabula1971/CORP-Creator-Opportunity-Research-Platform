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
REM    6. Launch uvicorn on http://127.0.0.1:8000 (blocks until Ctrl+C)
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

echo.
echo [corp] Starting API on http://127.0.0.1:8000
echo [corp] Ctrl+C to stop.
echo.
python -m uvicorn corp.api.app:app --host 127.0.0.1 --port 8000

REM Keep the window open after uvicorn exits so any traceback stays visible.
pause
endlocal
