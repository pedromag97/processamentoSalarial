@echo off
rem Copia de seguranca diaria da base de dados do LSC Presencas, para correr NO PC SERVIDOR
rem com o Agendador de Tarefas do Windows (ver docs\INSTALACAO.md, passo 5).
rem
rem Guarda um ficheiro por dia em DESTINO e apaga os que tiverem mais de DIAS_A_GUARDAR dias.
rem Se COPIA_FORA estiver preenchida, copia tambem o ficheiro para la (outro disco, ou uma
rem pasta sincronizada com a nuvem). Se essa pasta nao estiver disponivel na altura, a copia
rem local fica feita na mesma e o registo diz que a de fora falhou.
rem
rem A palavra-passe NAO fica neste ficheiro: o pg_dump vai busca-la ao ficheiro
rem %APPDATA%\postgresql\pgpass.conf do utilizador que corre a tarefa
rem (ver palavra_passe_das_copias.cmd).

setlocal

rem --- Ajustar estas linhas ao servidor ---
set "PG_BIN=C:\Program Files\PostgreSQL\18\bin"
set "DESTINO=D:\Copias-LSC-Presencas"
set "COPIA_FORA="
set "DIAS_A_GUARDAR=60"

set "BASE=lsc_presencas"
set "UTILIZADOR=lsc_app"

if not exist "%DESTINO%" mkdir "%DESTINO%" || goto :erro

rem Data no formato AAAA-MM-DD, independente das definicoes regionais do Windows.
for /f %%D in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmm"') do set "QUANDO=%%D"
set "NOME=lsc_presencas_%QUANDO%.dump"
set "FICHEIRO=%DESTINO%\%NOME%"

rem -w: nunca pergunta a palavra-passe (sem o pgpass.conf falha logo, em vez de ficar a espera).
"%PG_BIN%\pg_dump.exe" -w -h localhost -U %UTILIZADOR% -d %BASE% -F c -f "%FICHEIRO%"
if errorlevel 1 (
    if exist "%FICHEIRO%" del "%FICHEIRO%"
    goto :erro
)

rem Apaga as copias antigas.
forfiles /p "%DESTINO%" /m lsc_presencas_*.dump /d -%DIAS_A_GUARDAR% /c "cmd /c del @path" 2>nul

echo %date% %time% OK %FICHEIRO%>> "%DESTINO%\registo.txt"

if not defined COPIA_FORA exit /b 0
if not exist "%COPIA_FORA%\" goto :fora_falhou
copy /y "%FICHEIRO%" "%COPIA_FORA%\%NOME%" >nul || goto :fora_falhou
forfiles /p "%COPIA_FORA%" /m lsc_presencas_*.dump /d -%DIAS_A_GUARDAR% /c "cmd /c del @path" 2>nul
echo %date% %time% OK %COPIA_FORA%\%NOME%>> "%DESTINO%\registo.txt"
exit /b 0

:fora_falhou
echo %date% %time% FALHOU a copia para %COPIA_FORA% (a local ficou feita)>> "%DESTINO%\registo.txt"
exit /b 2

:erro
echo %date% %time% FALHOU>> "%DESTINO%\registo.txt"
exit /b 1
