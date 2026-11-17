# LSC Presenças — memória do projeto

App desktop de **presenças diárias e pré-processamento salarial mensal** do Groupe LSC
(LOUSACABO CONSTRUÇÕES LDA e +INNOVATION, cerca de 70 trabalhadores destacados em França).
A especificação completa está em [docs/ESPECIFICACAO.md](docs/ESPECIFICACAO.md); o estado do
trabalho está em [PROGRESSO.md](PROGRESSO.md).

A app **não** calcula IRS, TSU nem líquido, e não emite recibos: produz um mapa de
pré-processamento (PDF por trabalhador e Excel-resumo por empresa) para o contabilista.

## Ritual de início de sessão

1. `git pull`
2. `. .\scripts\ambiente.ps1` (com o ponto) e depois `uv sync`
3. `uv run python -m lsc_presencas migrar` e `uv run pytest`
4. Ler o `PROGRESSO.md` e dizer ao Pedro, em 3 linhas, onde ficámos e qual é o próximo passo.

Num PC novo basta `.\setup.ps1` (faz os passos 2 e 3 e carrega os dados de demonstração).

## Ritual de fim de sessão

1. `uv run ruff check .` e `uv run pytest` a passar.
2. Atualizar o `PROGRESSO.md`.
3. Commit com mensagem clara e `git push`.
4. Trabalho a meio: commit num branch `wip/<tema>`, push, e escrever no `PROGRESSO.md` o que
   falta. Nunca fica trabalho só local.

## Regras de trabalho

- Trabalhar por marcos (secção 9 da especificação). No fim de cada marco: testes a passar, a app
  arranca, e mostrar ao Pedro o que mudou. Não avançar para o marco seguinte sem aprovação.
- Toda a lógica de cálculo fica em `calculo.py`, puro (sem interface nem base de dados), com
  testes `pytest`. A interface só chama esse módulo.
- **Nunca inventar valores legais.** Valores monetários, taxas e limites vêm das tabelas de
  configuração editáveis na app. Valor não fornecido = campo vazio + aviso no ecrã.
- Interface, mensagens e nomes de domínio (tabelas, campos, funções) em português de Portugal.
- Responder ao Pedro sempre em português de Portugal.

## Dados pessoais

- **Nunca** vão para o Git: o Excel real, a base de dados, backups, PDF/Excel gerados e o `.env`.
- Desenvolvimento e testes usam só o seed de demonstração (`scripts/seed_demo.py`, nomes
  fictícios) e, para a importação, um Excel fictício em `tests/fixtures/`.
- O Excel real fica na pasta indicada por `LSC_DADOS_DIR` no `.env` de cada PC.
- Ao inspecionar o Excel real, não copiar nomes de trabalhadores para ficheiros do repositório.

## Stack

- Python 3.12 (gerido pelo `uv`; versões fixas no `uv.lock`), PySide6, SQLite com SQLAlchemy 2.x
  e Alembic, `openpyxl`, `reportlab`, `pytest`, `ruff`. PyInstaller no marco 7.
- Repositório: `github.com/pedromag97/processamentoSalarial` (privado), branch `main`.

## Comandos

Sempre depois de `. .\scripts\ambiente.ps1` (põe o venv fora do OneDrive, em
`%LOCALAPPDATA%\LSC-Presencas-dev\venv`, e usa os certificados do Windows no `uv`).

| Para | Comando |
|---|---|
| Abrir a app | `uv run python -m lsc_presencas` |
| Criar/atualizar a base de dados | `uv run python -m lsc_presencas migrar` |
| Dados de demonstração | `uv run python scripts/seed_demo.py` |
| Testes | `uv run pytest` |
| Lint e formatação | `uv run ruff check .` e `uv run ruff format .` |
| Nova migração | `uv run alembic revision --autogenerate -m "descrição" --rev-id 000N` |

## Estrutura

```
src/lsc_presencas/
  config.py       caminhos (LSC_APP_DIR, LSC_DADOS_DIR); nada de caminhos absolutos no código
  db.py           engine, sessões e migrar()
  modelos.py      modelo de dados
  dados_base.py   códigos de presença e feriados nacionais (carregamento idempotente)
  consultas.py    vigências (parâmetros e salário em vigor num dia)
  demo.py         dados de demonstração
  migracoes/      Alembic (dentro do pacote, para o PyInstaller)
  ui/             interface PySide6
scripts/          ambiente.ps1, seed_demo.py
tests/
```

## Decisões tomadas

- **Dinheiro e horas são `Decimal`**, guardados como texto (tipo `Valor`). Arredondamento a
  2 casas por rubrica; o total é a soma das rubricas já arredondadas.
- **Vigência:** `ParametrosEmpresa` e `SalarioBase` têm `inicio_vigencia`; aplica-se a linha mais
  recente que não seja posterior ao dia. O salário base não é um campo do trabalhador.
- **Códigos de presença:** todos os efeitos são atributos editáveis da tabela. A ajuda de custo
  tem três valores: `nao`, `sim`, `zona` (só se a zona da marcação for em França; usado no PR).
  Por defeito PF não acumula subsídio de alimentação e FJ não desconta salário.
- **Zona e feriado têm país** (`PT`/`FR`).
- **Trabalhador pode não ter empresa** (logo após a importação); o nº interno é atribuído pela
  app, porque o nº da folha `s-27` repete-se entre blocos.
- **Auditoria sem login:** "quem" é o utilizador do Windows.
- **Fecho do mês** vai gravar uma fotografia das rubricas calculadas (marco 6), para o Excel e
  os PDF baterem certo e não mudarem depois.
- **Dados base** (códigos, feriados) são carregados por `carregar_dados_base()`, que só
  acrescenta o que falta e nunca repõe o que o utilizador editou.
- Migrações com `render_as_batch=True` (SQLite) e um teste que falha se o modelo mudar sem
  migração.

## O que se sabe da folha `s-27` real (lida em 2026-11-17)

- Dias de K a NQ: 371 colunas, de 28/12/2026 a 02/01/2028. A data calcula-se pela posição.
- Quase sem marcações: só uma linha tem dados (`baixa`). A importação traz sobretudo
  trabalhadores, clientes e viaturas.
- Os títulos de zona (linhas 65 e 68) estão nas colunas dos dias, uma vez por semana.
- O bloco 2 (linhas 55–78) não tem cliente em nenhuma linha.
- A linha 5 tem 29 dias errados e a linha 53 tem 44.
- A folha `FM` não tem a empresa por trabalhador (AF/AG só têm título e total).
