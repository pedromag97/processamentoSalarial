@echo off
rem Cria a pasta com o executavel, fora do OneDrive:
rem   %LOCALAPPDATA%\LSC-Presencas-dev\dist\LSC-Presencas\LSC-Presencas.exe
cd /d "%~dp0.."
call scripts\ambiente.cmd || (pause & exit /b 1)
set "SAIDA=%LOCALAPPDATA%\LSC-Presencas-dev"

uv sync --quiet || goto :erro
uv run pyinstaller "%CD%\scripts\lsc_presencas_exe.py" ^
    --name LSC-Presencas ^
    --noconsole --noconfirm --clean ^
    --paths "%CD%\src" ^
    --add-data "%CD%\src\lsc_presencas\migracoes;lsc_presencas\migracoes" ^
    --exclude-module pytest --exclude-module pypdf --exclude-module pgserver ^
    --collect-all psycopg --collect-all psycopg_binary ^
    --hidden-import sqlalchemy.dialects.postgresql.psycopg ^
    --hidden-import keyring.backends.Windows --copy-metadata keyring ^
    --distpath "%SAIDA%\dist" ^
    --workpath "%SAIDA%\build" ^
    --specpath "%SAIDA%\build" || goto :erro

echo.
echo Pronto: %SAIDA%\dist\LSC-Presencas\LSC-Presencas.exe
echo Para instalar noutro PC, copia a pasta LSC-Presencas inteira.
echo Os dados ficam em %%APPDATA%%\LSC-Presencas (fora da pasta do programa).
if not "%1"=="--sem-pausa" pause
exit /b 0

:erro
echo.
echo Falhou. Ve a mensagem acima.
if not "%1"=="--sem-pausa" pause
exit /b 1
