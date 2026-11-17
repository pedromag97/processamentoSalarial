# Prepara um PC novo: venv, dependencias, .env, migracoes, dados de demonstracao e testes.
# Uso:  .\setup.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

. .\scripts\ambiente.ps1

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "O uv nao esta instalado. Instala-o com:" -ForegroundColor Yellow
    Write-Host "  winget install --id astral-sh.uv -e --source winget"
    Write-Host "Depois abre um PowerShell novo e corre outra vez .\setup.ps1"
    exit 1
}

function Passo($texto, [scriptblock]$acao) {
    Write-Host "== $texto" -ForegroundColor Cyan
    & $acao
    if ($LASTEXITCODE -ne 0) { throw "Falhou: $texto" }
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Criei o .env a partir do .env.example (ajusta o LSC_DADOS_DIR se precisares)."
}

Passo "Dependencias (uv sync)" { uv sync }
Passo "Migracoes e dados base" { uv run python -m lsc_presencas migrar }
Passo "Dados de demonstracao" { uv run python scripts/seed_demo.py }
Passo "Testes" { uv run pytest }

Write-Host ""
Write-Host "Pronto. Para abrir a app:  uv run python -m lsc_presencas" -ForegroundColor Green
