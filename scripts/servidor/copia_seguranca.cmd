@echo off
rem Copia de seguranca diaria da base de dados do LSC Presencas, para correr NO PC SERVIDOR
rem com o Agendador de Tarefas do Windows (ver docs\INSTALACAO.md, passo 5).
rem
rem Guarda um ficheiro por dia e apaga os que tiverem mais de 60 dias.
rem A palavra-passe NAO fica neste ficheiro: o pg_dump vai busca-la ao ficheiro
rem %APPDATA%\postgresql\pgpass.conf do utilizador que corre a tarefa.

setlocal

rem --- Ajustar estas tres linhas ao servidor ---
set "PG_BIN=C:\Program Files\PostgreSQL\17\bin"
set "DESTINO=D:\Copias-LSC-Presencas"
set "DIAS_A_GUARDAR=60"

set "BASE=lsc_presencas"
set "UTILIZADOR=lsc_app"

if not exist "%DESTINO%" mkdir "%DESTINO%" || goto :erro

rem Data no formato AAAA-MM-DD, independente das definicoes regionais do Windows.
for /f %%D in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmm"') do set "QUANDO=%%D"
set "FICHEIRO=%DESTINO%\lsc_presencas_%QUANDO%.dump"

"%PG_BIN%\pg_dump.exe" -h localhost -U %UTILIZADOR% -d %BASE% -F c -f "%FICHEIRO%" || goto :erro

rem Apaga as copias antigas.
forfiles /p "%DESTINO%" /m lsc_presencas_*.dump /d -%DIAS_A_GUARDAR% /c "cmd /c del @path" 2>nul

echo %date% %time% OK %FICHEIRO%>> "%DESTINO%\registo.txt"
exit /b 0

:erro
echo %date% %time% FALHOU>> "%DESTINO%\registo.txt"
exit /b 1
