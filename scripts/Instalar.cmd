@echo off
rem Instala o LSC Presencas neste PC: copia o programa e cria os atalhos.
rem
rem Nao e preciso instalar mais nada: esta pasta ja traz tudo o que o programa precisa
rem (Python, interface grafica, ligacao ao servidor). Nao precisa de ser administrador.
rem
rem Uso: duplo clique neste ficheiro, dentro da pasta LSC-Presencas que recebeu.

setlocal
set "ORIGEM=%~dp0"
if "%ORIGEM:~-1%"=="\" set "ORIGEM=%ORIGEM:~0,-1%"
set "DESTINO=%LOCALAPPDATA%\Programs\LSC-Presencas"

if not exist "%ORIGEM%\LSC-Presencas.exe" (
    echo Nao encontro o LSC-Presencas.exe ao lado deste ficheiro.
    echo Corra o Instalar.cmd de dentro da pasta LSC-Presencas completa.
    goto :fim_com_erro
)

tasklist /fi "imagename eq LSC-Presencas.exe" 2>nul | find /i "LSC-Presencas.exe" >nul
if not errorlevel 1 (
    echo O LSC Presencas esta aberto. Feche-o e corra este ficheiro outra vez.
    goto :fim_com_erro
)

if /i "%ORIGEM%"=="%DESTINO%" (
    echo O programa ja esta na pasta de instalacao. Vou so refazer os atalhos.
) else (
    echo A copiar o programa para %DESTINO% ...
    robocopy "%ORIGEM%" "%DESTINO%" /MIR /NFL /NDL /NJH /NJS /NP >nul
    if errorlevel 8 (
        echo A copia falhou. Confirme que tem espaco no disco e tente outra vez.
        goto :fim_com_erro
    )
)

echo A criar os atalhos ...
powershell -NoProfile -Command ^
  "$exe = Join-Path $env:LOCALAPPDATA 'Programs\LSC-Presencas\LSC-Presencas.exe';" ^
  "$w = New-Object -ComObject WScript.Shell;" ^
  "$nome = 'LSC Presen' + [char]0xE7 + 'as.lnk';" ^
  "foreach ($pasta in [Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs')) {" ^
  "  $a = $w.CreateShortcut((Join-Path $pasta $nome)); $a.TargetPath = $exe;" ^
  "  $a.WorkingDirectory = Split-Path $exe; $a.Description = 'LSC Presencas'; $a.Save() }"
if errorlevel 1 (
    echo Nao consegui criar os atalhos. O programa esta em:
    echo   %DESTINO%\LSC-Presencas.exe
    goto :fim_com_erro
)

echo.
echo Instalado. Abra o programa pelo atalho "LSC Presencas" no ambiente de trabalho.
echo.
echo Na primeira abertura, o antivirus pode demorar uns minutos a analisar o programa.
echo Se este PC vai usar o servidor do escritorio: no ecra de entrada, carregue em
echo "Ligacao ao servidor..." e preencha os dados que o administrador lhe deu.
echo Os dados que ja existirem neste PC nao sao alterados pela instalacao.
echo.
pause
exit /b 0

:fim_com_erro
echo.
pause
exit /b 1
