@echo off
rem Deixa os PCs de UMA rede ligarem-se a base de dados do LSC Presencas, neste PC servidor
rem (ver docs\INSTALACAO.md, passo 3). Correr COMO ADMINISTRADOR, com o programa fechado.
rem
rem Faz tres coisas:
rem   1. acrescenta a rede ao pg_hba.conf, so para esta base de dados e este utilizador
rem      (guarda antes uma copia em pg_hba.conf.antes-lsc);
rem   2. cria na firewall do Windows uma regra de entrada para a porta, limitada a essa rede
rem      e ao perfil de rede privado;
rem   3. reinicia o servico do PostgreSQL.
rem
rem Pode correr-se mais de uma vez: nao duplica nada. Para outra rede (por exemplo a da VPN),
rem mudar REDE e NOME_DA_REDE e correr outra vez.

setlocal

rem --- Ajustar estas linhas ao servidor ---
set "PG_VERSAO=18"
set "PORTA=5432"
set "REDE=192.168.1.0/24"
set "NOME_DA_REDE=escritorio"

set "BASE=lsc_presencas"
set "UTILIZADOR=lsc_app"
set "DADOS=C:\Program Files\PostgreSQL\%PG_VERSAO%\data"
set "SERVICO=postgresql-x64-%PG_VERSAO%"
set "REGRA=LSC Presencas - PostgreSQL - %NOME_DA_REDE%"
set "LINHA=host  %BASE%  %UTILIZADOR%  %REDE%  scram-sha-256"

net session >nul 2>&1
if errorlevel 1 (
    echo Isto tem de ser corrido como administrador:
    echo botao direito no ficheiro e "Executar como administrador".
    goto :fim_erro
)

if not exist "%DADOS%\pg_hba.conf" (
    echo Nao encontro %DADOS%\pg_hba.conf
    echo Confirma a linha PG_VERSAO no topo deste ficheiro.
    goto :fim_erro
)

echo 1. pg_hba.conf
findstr /l /c:"%LINHA%" "%DADOS%\pg_hba.conf" >nul
if not errorlevel 1 (
    echo    A rede %REDE% ja la estava.
    goto :firewall
)
if not exist "%DADOS%\pg_hba.conf.antes-lsc" copy /y "%DADOS%\pg_hba.conf" "%DADOS%\pg_hba.conf.antes-lsc" >nul || goto :erro
>>"%DADOS%\pg_hba.conf" echo.
>>"%DADOS%\pg_hba.conf" echo # LSC Presencas: rede %NOME_DA_REDE%
>>"%DADOS%\pg_hba.conf" echo %LINHA%
if errorlevel 1 goto :erro
echo    Acrescentada a rede %REDE%.

:firewall
echo 2. Firewall do Windows
netsh advfirewall firewall delete rule name="%REGRA%" >nul 2>&1
netsh advfirewall firewall add rule name="%REGRA%" dir=in action=allow protocol=TCP localport=%PORTA% remoteip=%REDE% profile=private >nul || goto :erro
echo    Regra "%REGRA%": porta %PORTA%, so da rede %REDE%, perfil privado.

echo 3. Reiniciar o servico %SERVICO%
net stop %SERVICO% >nul 2>&1
net start %SERVICO% >nul || goto :erro
echo    Servico a correr.

echo.
echo Pronto. Nos outros PCs, em "Ligacao ao servidor", escreve o endereco deste PC.
pause
exit /b 0

:erro
echo.
echo Falhou. Ve a mensagem acima.
:fim_erro
pause
exit /b 1
