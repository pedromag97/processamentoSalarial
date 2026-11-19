@echo off
rem Prepara o ficheiro onde o pg_dump vai buscar a palavra-passe da app, para a copia de
rem seguranca diaria nao a pedir. Correr com o utilizador que vai correr a tarefa agendada
rem (NAO como administrador).
rem
rem Abre o ficheiro no Bloco de Notas: trocar A_PALAVRA_PASSE_DA_APP pela palavra-passe do
rem utilizador lsc_app, guardar e fechar. O ficheiro fica na pasta pessoal desse utilizador.

setlocal
set "PASTA=%APPDATA%\postgresql"
set "FICHEIRO=%PASTA%\pgpass.conf"

if not exist "%PASTA%" mkdir "%PASTA%"
if not exist "%FICHEIRO%" >"%FICHEIRO%" echo localhost:5432:*:lsc_app:A_PALAVRA_PASSE_DA_APP

echo Troca A_PALAVRA_PASSE_DA_APP pela palavra-passe do lsc_app, guarda e fecha o Bloco de Notas.
notepad "%FICHEIRO%"
