@echo off
rem Abre a app. Pode ser usado com duplo clique.
cd /d "%~dp0"
call scripts\ambiente.cmd || (pause & exit /b 1)
uv run python -m lsc_presencas
if errorlevel 1 pause
