# Prepara a sessao do PowerShell para trabalhar no projeto.
# Uso:  . .\scripts\ambiente.ps1     (com o ponto no inicio)
#
# - O venv fica fora da pasta do projeto (que pode estar no OneDrive).
# - Garante que o uv instalado pelo winget esta no PATH desta sessao.

$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:LOCALAPPDATA "LSC-Presencas-dev\venv"

# Usa os certificados do Windows (necessario quando um antivirus inspeciona as ligacoes HTTPS).
$env:UV_SYSTEM_CERTS = "true"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    # O winget acrescenta a pasta do uv ao PATH do utilizador, mas so os terminais abertos
    # depois da instalacao o veem. Aqui vai-se buscar esse PATH atualizado.
    $pathUtilizador = [Environment]::GetEnvironmentVariable("PATH", "User")
    if ($pathUtilizador) { $env:PATH = "$env:PATH;$pathUtilizador" }
}
