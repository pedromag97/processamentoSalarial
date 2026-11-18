@echo off
rem Abre a app sem janela de consola. Pode ser usado com duplo clique.
rem (A janela preta aparece so um instante, enquanto confirma as dependencias.)
cd /d "%~dp0"
call scripts\ambiente.cmd || (pause & exit /b 1)
uv sync --quiet
if errorlevel 1 (
    echo Nao foi possivel preparar o ambiente. Corre setup.cmd para ver o erro.
    pause
    exit /b 1
)
start "" "%UV_PROJECT_ENVIRONMENT%\Scripts\pythonw.exe" -m lsc_presencas
