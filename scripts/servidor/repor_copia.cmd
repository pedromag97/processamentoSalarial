@echo off
rem Repoe uma copia de seguranca (.dump) da base de dados do LSC Presencas. Correr NO PC
rem SERVIDOR, com o utilizador que tem o pgpass.conf (ver palavra_passe_das_copias.cmd).
rem
rem   repor_copia.cmd
rem       ENSAIO com a copia mais recente: repoe-a numa base de dados a parte
rem       (lsc_presencas_teste) e mostra quantos registos tem. Nao toca nos dados verdadeiros.
rem       Pede uma vez a palavra-passe do administrador do servidor (postgres), para criar
rem       essa base de dados.
rem
rem   repor_copia.cmd "C:\caminho\ficheiro.dump"
rem       O mesmo ensaio, com a copia indicada.
rem
rem   repor_copia.cmd "C:\caminho\ficheiro.dump" --a-serio
rem       SUBSTITUI os dados verdadeiros pelos da copia. So com o programa fechado em todos os
rem       PCs. Antes de substituir faz uma copia de seguranca do que la esta.
rem
rem Para o ensaio, a linha do pgpass.conf tem de servir para qualquer base de dados:
rem     localhost:5432:*:lsc_app:A_PALAVRA_PASSE_DA_APP

setlocal

rem --- Ajustar estas linhas ao servidor (iguais as do copia_seguranca.cmd) ---
set "PG_BIN=C:\Program Files\PostgreSQL\18\bin"
set "DESTINO=D:\Copias-LSC-Presencas"

set "BASE=lsc_presencas"
set "TESTE=lsc_presencas_teste"
set "UTILIZADOR=lsc_app"
set "CONTAR=select 'empresas', count(*) from empresa union all select 'trabalhadores', count(*) from trabalhador union all select 'marcacoes', count(*) from marcacao union all select 'lancamentos', count(*) from lancamento_manual union all select 'meses fechados', count(*) from fecho_mes union all select 'contas', count(*) from utilizador union all select 'auditoria', count(*) from auditoria"

set "FICHEIRO=%~1"
if /i "%~2"=="--a-serio" goto :a_serio
if not "%~2"=="" goto :uso

rem ---------------------------------------------------------------- ensaio
if defined FICHEIRO goto :tem_ficheiro
for /f "delims=" %%F in ('dir /b /o-d "%DESTINO%\lsc_presencas_*.dump" 2^>nul') do if not defined FICHEIRO set "FICHEIRO=%DESTINO%\%%F"
if not defined FICHEIRO (
    echo Nao ha copias em %DESTINO%
    goto :fim_erro
)
:tem_ficheiro
if not exist "%FICHEIRO%" (
    echo Nao encontro o ficheiro %FICHEIRO%
    goto :fim_erro
)

echo ENSAIO: repor a copia
echo     %FICHEIRO%
echo na base de dados de teste %TESTE%. Os dados verdadeiros nao sao tocados.
echo.
echo 1. Criar a base de dados de teste.
echo    Escreve a palavra-passe do administrador do servidor (postgres); nao aparece no ecra.
"%PG_BIN%\psql.exe" -h localhost -U postgres -d postgres -q -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS %TESTE%" -c "CREATE DATABASE %TESTE% OWNER %UTILIZADOR% ENCODING 'UTF8' TEMPLATE template0" -c "REVOKE ALL ON DATABASE %TESTE% FROM PUBLIC"
if errorlevel 1 goto :erro

"%PG_BIN%\psql.exe" -w -h localhost -U %UTILIZADOR% -d %TESTE% -q -c "select 1" >nul 2>&1
if errorlevel 1 (
    echo.
    echo O pgpass.conf so serve para a base de dados %BASE%.
    echo Corre o palavra_passe_das_copias.cmd e, na linha, troca  :%BASE%:  por  :*:
    echo Depois corre isto outra vez.
    goto :fim_erro
)

echo 2. Repor a copia na base de dados de teste.
"%PG_BIN%\pg_restore.exe" -w -h localhost -U %UTILIZADOR% -d %TESTE% --no-owner --single-transaction "%FICHEIRO%"
if errorlevel 1 goto :erro

echo 3. O que a copia tem:
"%PG_BIN%\psql.exe" -w -h localhost -U %UTILIZADOR% -d %TESTE% -A -t -F ": " -c "%CONTAR%"
if errorlevel 1 goto :erro
echo.
echo    O que a base de dados verdadeira tem agora (pode ter mais, se trabalharam depois da copia):
"%PG_BIN%\psql.exe" -w -h localhost -U %UTILIZADOR% -d %BASE% -A -t -F ": " -c "%CONTAR%"

echo.
echo A copia repoe-se bem. A base de dados de teste tem dados pessoais: convem apaga-la.
set "APAGAR="
set /p "APAGAR=Apagar agora a base de dados de teste? (S/N) "
if /i not "%APAGAR%"=="S" goto :fim_ok
echo    Palavra-passe do administrador do servidor (postgres):
"%PG_BIN%\psql.exe" -h localhost -U postgres -d postgres -q -c "DROP DATABASE IF EXISTS %TESTE%"
if errorlevel 1 goto :erro
echo    Apagada.
goto :fim_ok

rem ---------------------------------------------------------------- a serio
:a_serio
if not exist "%FICHEIRO%" (
    echo Nao encontro o ficheiro %FICHEIRO%
    goto :fim_erro
)
echo ATENCAO: isto SUBSTITUI os dados verdadeiros do LSC Presencas pelos da copia
echo     %FICHEIRO%
echo Tudo o que foi feito depois dessa copia deixa de estar na base de dados.
echo O programa tem de estar fechado em todos os PCs.
echo.
set "CONFIRMA="
set /p "CONFIRMA=Para continuar, escreve REPOR e carrega em Enter: "
if not "%CONFIRMA%"=="REPOR" (
    echo Nada foi alterado.
    goto :fim_erro
)

set "LIGADOS="
set "TMP_LIGADOS=%TEMP%\lsc_presencas_ligados.txt"
"%PG_BIN%\psql.exe" -w -h localhost -U %UTILIZADOR% -d %BASE% -A -t -c "select count(*) from pg_stat_activity where datname = '%BASE%' and pid != pg_backend_pid()" > "%TMP_LIGADOS%" 2>nul
if not errorlevel 1 set /p LIGADOS=<"%TMP_LIGADOS%"
del "%TMP_LIGADOS%" 2>nul
if not defined LIGADOS (
    echo Nao consegui ligar ao servidor. Nada foi alterado.
    goto :fim_erro
)
if not "%LIGADOS%"=="0" (
    echo Ligacoes abertas a base de dados: %LIGADOS%. O programa esta aberto nalgum PC.
    echo Fecha-o em todos e tenta outra vez. Nada foi alterado.
    goto :fim_erro
)

echo 1. Copia de seguranca do que la esta agora.
call "%~dp0copia_seguranca.cmd"
rem 1 = a copia falhou; 2 = a local ficou feita e so a de fora falhou (chega para continuar).
if %errorlevel%==1 (
    echo A copia de seguranca falhou. Nada foi alterado.
    goto :fim_erro
)

echo 2. Repor a copia.
"%PG_BIN%\pg_restore.exe" -w -h localhost -U %UTILIZADOR% -d %BASE% --clean --if-exists --no-owner --single-transaction "%FICHEIRO%"
if errorlevel 1 (
    echo.
    echo Falhou. A base de dados ficou como estava: a reposicao e tudo ou nada.
    goto :fim_erro
)

echo 3. O que ficou na base de dados:
"%PG_BIN%\psql.exe" -w -h localhost -U %UTILIZADOR% -d %BASE% -A -t -F ": " -c "%CONTAR%"
echo.
echo Reposta. Ja se pode abrir o programa.
goto :fim_ok

:uso
echo Uso:
echo     repor_copia.cmd                          ensaio com a copia mais recente
echo     repor_copia.cmd "ficheiro.dump"          ensaio com essa copia
echo     repor_copia.cmd "ficheiro.dump" --a-serio    substitui os dados verdadeiros
goto :fim_erro

:erro
echo.
echo Falhou. Ve a mensagem acima.
:fim_erro
pause
exit /b 1

:fim_ok
pause
exit /b 0
