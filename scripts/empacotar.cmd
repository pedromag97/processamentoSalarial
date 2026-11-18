@echo off
rem Cria a pasta com o executavel, fora do OneDrive:
rem   %LOCALAPPDATA%\LSC-Presencas-dev\dist\LSC-Presencas\LSC-Presencas.exe
cd /d "%~dp0.."
call scripts\ambiente.cmd || (pause & exit /b 1)
set "SAIDA=%LOCALAPPDATA%\LSC-Presencas-dev"

uv sync --quiet || goto :erro

rem As bibliotecas OpenSSL tem de ser as do proprio Python. Sem isto, o PyInstaller pode ir
rem buscar outras com o mesmo nome ao PATH (por exemplo as do Git), e a ligacao ao servidor
rem falha dentro do executavel com "DLL load failed while importing _ssl".
for /f "delims=" %%P in ('uv run python -c "import sys; print(sys.base_prefix)"') do set "PYHOME=%%P"
if not exist "%PYHOME%\DLLs\libcrypto-3-x64.dll" (
    echo Nao encontro as bibliotecas OpenSSL do Python em %PYHOME%\DLLs
    goto :erro
)
set "PATH=%PYHOME%;%PYHOME%\DLLs;%PATH%"

uv run pyinstaller "%CD%\scripts\lsc_presencas_exe.py" ^
    --name LSC-Presencas ^
    --noconsole --noconfirm --clean ^
    --paths "%CD%\src" ^
    --add-data "%CD%\src\lsc_presencas\migracoes;lsc_presencas\migracoes" ^
    --add-binary "%PYHOME%\DLLs\libcrypto-3-x64.dll;." ^
    --add-binary "%PYHOME%\DLLs\libssl-3-x64.dll;." ^
    --exclude-module pytest --exclude-module pypdf --exclude-module pgserver ^
    --collect-all psycopg --collect-all psycopg_binary ^
    --hidden-import sqlalchemy.dialects.postgresql.psycopg ^
    --hidden-import keyring.backends.Windows --copy-metadata keyring ^
    --distpath "%SAIDA%\dist" ^
    --workpath "%SAIDA%\build" ^
    --specpath "%SAIDA%\build" || goto :erro

copy /y "%CD%\scripts\Instalar.cmd" "%SAIDA%\dist\LSC-Presencas\Instalar.cmd" >nul || goto :erro

echo.
echo Pronto: %SAIDA%\dist\LSC-Presencas\LSC-Presencas.exe
echo Para instalar noutro PC: copia a pasta LSC-Presencas inteira e corre la o Instalar.cmd.
echo Os dados ficam em %%APPDATA%%\LSC-Presencas (fora da pasta do programa).
if not "%1"=="--sem-pausa" pause
exit /b 0

:erro
echo.
echo Falhou. Ve a mensagem acima.
if not "%1"=="--sem-pausa" pause
exit /b 1
