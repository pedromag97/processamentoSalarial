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
Se o PowerShell recusar scripts (`running scripts is disabled`), usar `setup.cmd` e `abrir.cmd`;
dentro do Claude Code, as variáveis do `ambiente.ps1` podem ser definidas à mão no comando.

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
  e Alembic, `openpyxl`, `reportlab`, `pytest`, `ruff`; `pypdf` só nos testes (ler os PDF
  gerados) e `pyinstaller` só para empacotar.
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
| Criar o executável | `scripts\empacotar.cmd` (sai em `%LOCALAPPDATA%\LSC-Presencas-dev\dist`) |

Neste PC os comandos são lentos (a bateria de testes leva uns 3 minutos): correr os testes em
segundo plano e, ao investigar uma falha, correr só o ficheiro em causa.

## Estrutura

```
src/lsc_presencas/
  config.py       caminhos (LSC_APP_DIR, LSC_DADOS_DIR); nada de caminhos absolutos no código
  db.py           engine, sessões e migrar()
  modelos.py      modelo de dados
  dados_base.py   códigos de presença e feriados nacionais (carregamento idempotente)
  consultas.py    vigências (parâmetros e salário em vigor num dia)
  calculo.py      cálculo do mês de um trabalhador; puro, sem base de dados nem interface
  preprocessamento.py  lê a base de dados e chama o calculo.py
  presencas.py    marcações: interpretar células, gravar com auditoria, meses fechados
  importacao.py   importação única da s-27: ler, planear (duplicados) e gravar, com relatório
  mapa.py         mapa do mês de uma empresa (MapaMes): base do ecrã de fecho, do Excel e dos PDF
  fecho.py        alertas, fechar (fotografia + backup) e reabrir (motivo obrigatório)
  lancamentos.py  auditoria e bloqueio de mês fechado nos lançamentos manuais
  backups.py      cópias de segurança da base de dados (últimas 30)
  exportacao.py   gera os ficheiros do mês; exportar_excel.py e exportar_pdf.py fazem cada um
  relatorios.py   férias e prevenção (anuais), dias por cliente e por viatura; para_excel()
  auditoria.py    registar() e listar() a auditoria (ecrã Auditoria e histórico da ficha)
  demo.py         dados de demonstração
  migracoes/      Alembic (dentro do pacote, para o PyInstaller)
  ui/             interface PySide6
    app.py          janela principal e navegação
    tabela.py       tabela editável e formulário genéricos (Coluna, ModeloTabela, VistaTabela)
    definicoes.py   colunas de cada tabela: é aqui que se acrescenta um campo aos ecrãs
    ecra_tabelas.py, ecra_trabalhadores.py
    grelha.py       modelos da grelha de presenças e do rodapé de totais por dia
    ecra_presencas.py  dashboard: três tabelas sincronizadas, teclado, filtros
    ecra_lancamentos.py, ecra_fecho.py, periodo.py (seletor de mês)
    ecra_relatorios.py, ecra_auditoria.py, lista.py (tabela só de leitura)
    formatos.py     texto <-> números e datas (vírgula decimal, dd/mm/aaaa)
scripts/          ambiente.ps1/.cmd, seed_demo.py, empacotar.cmd, lsc_presencas_exe.py
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
- **Fecho do mês:** `fecho.fechar()` grava uma fotografia em JSON (`FechoMes.fotografia` e uma
  linha `FechoTrabalhador` por pessoa). `fecho.mapa_do_mes()` devolve a fotografia se o mês
  estiver fechado e o cálculo ao vivo se estiver aberto; o Excel e os PDF saem sempre desse
  `MapaMes`, por isso batem certo e não mudam depois. Erros impedem o fecho; avisos pedem
  confirmação. Reabrir exige motivo, apaga a fotografia e fica na auditoria. Há backup antes
  de fechar e antes de reabrir.
- **Lançamentos manuais:** gravam-se pela tabela genérica com o gancho `ao_gravar`
  (`lancamentos.registar`), que escreve a auditoria e recusa meses fechados.
- **Ficheiros gerados:** `saidas\AAAA-MM_<EMPRESA>\` na pasta da app (nunca no repositório).
  Mês aberto = pasta e ficheiros marcados como provisórios.
- **Auditoria:** além das marcações, dos lançamentos e do fecho, ficam registadas as
  alterações à ficha do trabalhador e ao salário base. O histórico da ficha filtra pelo nº
  interno guardado no JSON do registo (`"trabalhador": N`).
- **Backups:** ao abrir a app (antes das migrações), antes de fechar e de reabrir um mês, e à
  mão no ecrã «Base de dados». Guardam-se os últimos 30.
- **Executável:** PyInstaller em modo pasta, sem consola. As migrações vão como dados
  (`--add-data`). O executável nunca lê o `.env`: usa `%APPDATA%\LSC-Presencas`, a não ser
  que a variável de ambiente `LSC_APP_DIR` esteja definida. A pasta `dist` fica fora do
  OneDrive e do Git.
- **Testes:** o `conftest.py` aponta `LSC_APP_DIR` para uma pasta temporária (nenhum teste
  escreve na pasta de dados verdadeira) e faz `gc.collect()` no fim de cada teste, para os
  ecrãs Qt serem destruídos antes de o Python sair.
- **Cálculo:** `calculo.calcular_mes()` devolve um `Resultado` com rubricas (cada uma com a
  fórmula em texto), contagens e alertas. Um valor em falta nunca vira zero: a rubrica fica com
  `total=None`, o resultado fica `incompleto` e há um alerta. Os pressupostos assumidos estão
  no `PROGRESSO.md` e ainda não foram confirmados com o contabilista.
- **Interface:** uma única sessão SQLAlchemy para toda a janela (`expire_on_commit=True`). Os
  erros aparecem numa linha por baixo da tabela, não em caixas modais (também para os testes
  correrem em `offscreen`). Os ecrãs testam-se pelo modelo (`setData`), sem simular cliques.
- **Marcações:** só se alteram por `presencas.aplicar_alteracoes()`, que grava em lote (tudo ou
  nada), recusa meses fechados e escreve a auditoria. A grelha nunca mexe em `Marcacao` diretamente.
- **Grelha:** não usa objetos do modelo (lê só colunas, com duas consultas) para abrir depressa.
  São três `QTableView` sobre o mesmo modelo (fixas, dias, totais) mais um rodapé igual.
  Cada ação (colar, aplicar, copiar semana) é um só passo de Ctrl+Z.
- **Importação:** o assistente não grava nada até ao botão "Importar"; a gravação é tudo ou
  nada. Quem já existe com o mesmo nome não é criado outra vez. Os testes usam só
  `tests/fixtures/s27_ficticio.xlsx` (gerado por `gerar_s27_ficticio.py`); nunca o Excel real.
- **Abrir a app:** `abrir.cmd` usa `pythonw` (sem consola). Um erro de arranque fica em
  `erro.log` na pasta da app.
- **Scripts:** há `.ps1` e `.cmd` equivalentes (`setup`, `ambiente`, e `abrir.cmd`), porque um
  dos PCs bloqueia a execução de scripts PowerShell. Não se altera a política de execução.
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
