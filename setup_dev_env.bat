@echo off
setlocal

echo ============================================================
echo   BARDO AI - SETUP AMBIENTE DI SVILUPPO LOCALE
echo ============================================================
echo.

REM 1. Configurazione Git Hooks
echo [1/3] Configurazione Git Hooks...
git config core.hooksPath .githooks
if errorlevel 1 (
    echo       [ATTENZIONE] Impossibile configurare core.hooksPath. Assicurati che Git sia installato.
) else (
    echo       [OK] Hooks di sicurezza e test collegati con successo.
)
echo.

REM 2. Verifica Identita Git corrente
echo [2/3] Verifica Identita Git corrente...
for /f "delims=" %%a in ('git config user.name 2^>nul') do set "GIT_NAME=%%a"
for /f "delims=" %%b in ('git config user.email 2^>nul') do set "GIT_EMAIL=%%b"

if defined GIT_NAME (
    echo       Autore rilevato: %GIT_NAME% ^<%GIT_EMAIL%^>
) else (
    echo       [NOTA] Nessun autore Git configurato.
    echo       Puoi impostare la tua identita con:
    echo         git config user.name "Tuo Nome"
    echo         git config user.email "tua_email@example.com"
)
echo.

REM 3. Verifica Ambiente Python
echo [3/3] Verifica Ambiente Virtuale Python...
if exist ".venv\Scripts\python.exe" (
    echo       [OK] Ambiente virtuale .venv rilevato.
) else (
    echo       [NOTA] Ambiente .venv non trovato. Puoi crearlo con:
    echo         python -m venv .venv
    echo         .\.venv\Scripts\pip install -r requirements.txt
)
echo.

echo ============================================================
echo   SETUP COMPLETATO CON SUCCESSO!
echo ============================================================
echo.
pause
