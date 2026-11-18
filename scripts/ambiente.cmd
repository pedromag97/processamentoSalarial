@echo off
rem Prepara o ambiente (equivalente ao ambiente.ps1, para PCs onde o PowerShell bloqueia scripts).
rem Uso dentro de outro .cmd:  call scripts\ambiente.cmd

set "UV_PROJECT_ENVIRONMENT=%LOCALAPPDATA%\LSC-Presencas-dev\venv"
set "UV_SYSTEM_CERTS=true"

where uv >nul 2>nul
if errorlevel 1 (
    for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_*") do set "PATH=%%D;%PATH%"
)
where uv >nul 2>nul
if errorlevel 1 (
    echo O uv nao esta instalado. Instala-o com:
    echo   winget install --id astral-sh.uv -e --source winget
    exit /b 1
)
exit /b 0
