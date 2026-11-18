@echo off
rem Prepara um PC novo (equivalente ao setup.ps1, para PCs onde o PowerShell bloqueia scripts).
cd /d "%~dp0"
call scripts\ambiente.cmd || (pause & exit /b 1)

if not exist .env (
    copy .env.example .env >nul
    echo Criei o .env a partir do .env.example ^(ajusta o LSC_DADOS_DIR se precisares^).
)

echo == Dependencias
uv sync || goto :erro
echo == Migracoes e dados base
uv run python -m lsc_presencas migrar || goto :erro
echo == Dados de demonstracao
uv run python scripts/seed_demo.py || goto :erro
echo == Testes
uv run pytest || goto :erro

echo.
echo Pronto. Para abrir a app: abrir.cmd
pause
exit /b 0

:erro
echo.
echo Falhou. Ve a mensagem acima.
pause
exit /b 1
