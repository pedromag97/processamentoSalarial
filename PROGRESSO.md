# Progresso

## Marco atual

**Marco 5 concluído** (2026-11-18), à espera da aprovação do Pedro para começar o marco 6.

A importação real ainda **não foi feita**: só se ensaiou a leitura do Excel real (sem gravar).
Fica para o Pedro a fazer no PC do escritório, pelo assistente.

O cálculo (marco 2) foi feito com pressupostos (lista abaixo) que o Pedro mandou assumir; falta
confirmá-los com o contabilista.

## Próximo passo

Marco 6: fecho do mês por empresa (alertas, pré-visualização, fechar/reabrir com motivo,
fotografia das rubricas) e exportação para Excel e PDF.

## Checklist

### Marco 1 — repositório, estrutura e modelo de dados
- [x] Repositório Git (`pedromag97/processamentoSalarial`), `.gitignore`, `.env.example`
- [x] `CLAUDE.md`, `PROGRESSO.md`, `docs/ESPECIFICACAO.md`
- [x] Ambiente reproduzível: `uv.lock`, `.python-version`, `setup.ps1`, `scripts/ambiente.ps1`
- [x] Modelo de dados e migração Alembic inicial (`0001`)
- [x] Carregamento dos 10 códigos de presença e dos feriados nacionais de 2026 e 2027
- [x] Seed de demonstração (`scripts/seed_demo.py`, 24 trabalhadores fictícios, janeiro de 2027)
- [x] Testes do modelo, das migrações, do seed e de arranque da janela
- [x] Janela principal mínima (mostra o estado da base de dados)

### Marco 2 — `calculo.py`
- [x] Contagens por código, respeitando admissão e saída
- [x] Salário base processado (descontos e proporcional)
- [x] Subsídio de alimentação e ajuda de custo França (isento/sujeito, limite vazio ou preenchido)
- [x] Prevenção
- [x] Horas extra (dia útil, descanso, feriado)
- [x] Lançamentos manuais e total ilíquido estimado
- [x] Validações e alertas
- [x] `preprocessamento.py`: lê a base de dados e chama o cálculo

### Marco 3 — ecrãs de tabelas e trabalhadores
- [x] Janela principal com navegação (Início, Trabalhadores, Tabelas)
- [x] Tabela editável genérica (`ui/tabela.py`): gravação célula a célula, linha nova pendente
      até ter os campos obrigatórios, mensagens de erro, aviso de valores por preencher
- [x] Tabelas: empresas, clientes, viaturas, zonas, códigos, feriados, parâmetros com vigência
- [x] Trabalhadores: lista com pesquisa e filtro de inativos; ficha com dados, valores de
      exceção e histórico do salário base
- [ ] Ficha: histórico de alterações (fica para o marco 7, com a auditoria)

### Marco 4 — dashboard de presenças
- [x] `presencas.py`: interpretar `P+2`, gravar em lote com auditoria, bloquear meses fechados
- [x] Grelha agrupada por Empresa → Cliente (grupos recolhíveis), vista mensal e semanal
- [x] Colunas fixas à esquerda, totais à direita, rodapé com presentes por dia e por cliente
- [x] Teclado: escrever o código, Enter desce, Delete limpa, Ctrl+C / Ctrl+V / Ctrl+Z
- [x] Aplicar um código à seleção (a escrever ou pelos botões), copiar semana anterior
- [x] Filtros por empresa, cliente, viatura, zona, inativos e pesquisa por nome
- [x] Teste de desempenho: 104 trabalhadores × 31 dias em menos de 1 s
- [x] `abrir.cmd` e `setup.cmd`, para PCs onde o PowerShell bloqueia scripts `.ps1`
- [ ] Por verificar à mão pelo Pedro: "marcar um mês para 70 trabalhadores em menos de 10 min"

### Marco 5 — importação da `s-27`
- [x] `importacao.py`: ler (datas pela posição da coluna), planear (duplicados) e gravar
      (tudo ou nada), com relatório
- [x] Excel fictício `tests/fixtures/s27_ficticio.xlsx` e o script que o gera
- [x] Assistente em "Base de dados": ficheiro, códigos antigos, nomes repetidos, empresas em
      massa, confirmação e relatório (guardado em `saidas/` na pasta da app)
- [x] Sugestão de empresa pelos nomes das folhas dos mapas de férias (LOUSA / LUSOC)
- [x] Ensaio de leitura com o Excel real: 58 linhas, 4 nomes repetidos (linhas 10/69, 11/12,
      26/74, 27/72), 73 discrepâncias, 24 viaturas, só o valor `baixa`; 21 de 54 com sugestão
      de empresa
- [x] `abrir.cmd` passa a abrir a app sem janela de consola; erros de arranque vão para
      `erro.log` na pasta da app e para uma caixa de mensagem
- [ ] Importação real, pelo Pedro

### Marcos seguintes
- [ ] 6 — Fecho do mês, alertas, Excel e PDF
- [ ] 7 — Relatórios, backups, auditoria, PyInstaller

## Decisões tomadas

| Data | Decisão |
|---|---|
| 2026-11-17 | Repositório `processamentoSalarial` (em vez de `lsc-presencas`), em `OneDrive\Documentos\git`, com o venv fora do OneDrive. |
| 2026-11-17 | `uv` para o Python 3.12 e as dependências. |
| 2026-11-17 | Salário base com vigência (`SalarioBase`), em vez de campo do trabalhador. |
| 2026-11-17 | Valores `Decimal` guardados como texto; arredondamento a 2 casas por rubrica. |
| 2026-11-17 | Zona e feriado com país; ajuda de custo do código com `nao`/`sim`/`zona`. |
| 2026-11-17 | Nº interno atribuído pela app; o nº da `s-27` fica só no relatório de importação. |
| 2026-11-17 | Auditoria usa o utilizador do Windows. |
| 2026-11-17 | O fecho do mês grava uma fotografia das rubricas (a fazer no marco 6). |
| 2026-11-18 | O Pedro mandou avançar com o marco 2 usando os pressupostos abaixo. |

## Pressupostos do cálculo (assumidos em 2026-11-18, por confirmar com o contabilista)

Estão implementados e testados em `calculo.py`. Se algum estiver errado, muda-se aí.

1. **PR "conforme zona":** dá ajuda de custo só quando a zona da marcação é em França.
2. **Proporcional de entrada/saída:** salário base ÷ divisor × dias de calendário de contrato,
   sem nunca passar do salário base. Mês de contrato completo = salário base inteiro.
3. **Feriados:** contam só os feriados portugueses da tabela (o contrato é português). Horas
   extra num feriado português têm o acréscimo de descanso/feriado, mesmo a trabalhar em França.
   Os feriados franceses não contam.
4. **Limites de isenção:** são valores por dia. Isento = dias × mínimo(valor, limite).
5. **Horas extra em dia útil:** a "1.ª hora" conta-se por dia.
6. **PF não acumula subsídio de alimentação** (flag editável no código PF).
7. **FJ não desconta o salário** (flag editável no código FJ).
8. **AT:** desconta o salário como a baixa e aparece nas contagens e na descrição do desconto.
   Não há rubrica própria para o que a seguradora paga.
9. **Acréscimos de horas extra:** os da especificação (25%, 37,5%, 50%), editáveis nos parâmetros.
   Não se assumiu nenhum contrato coletivo.
10. **Valor/hora de exceção:** substitui o valor/hora calculado; os acréscimos aplicam-se na mesma.
11. **Desconto por faltas:** nunca ultrapassa o salário do período (o salário não fica negativo).
12. **Salário e parâmetros com vigência:** usa-se o que está em vigor no último dia de contrato
    dentro do mês (uma mudança a meio do mês não é repartida).
13. **Rubricas sem dias não aparecem**, e por isso não geram alerta de parâmetro em falta.
14. **Horas extra num código não trabalhado** (ex.: `FE+2`) são pagas, mas pedem confirmação.

## Dúvidas em aberto

### Não bloqueiam (valores a preencher na app)
- Subsídio de alimentação, ajuda de custo França e prevenção, por empresa.
- Limites de isenção fiscal (com o contabilista).

### Da importação (assumido em 2026-11-18; o assistente deixa sempre confirmar)
- "Lusoc" foi tratado como a +INNOVATION, só para sugerir a empresa. Por confirmar.
- As zonas importadas (`45 Orleans`, `64 Biarritz`) ficam com o país França.
- Há um par de nomes repetidos dentro do próprio bloco 1 (linhas 11 e 12).

### Outras
- Um trabalhador pode mudar de empresa a meio do ano?
- Fins de semana sem marcação geram alerta ou são normais?
- O código antigo `s` não aparece na folha de 2027; só interessa se se importarem anos anteriores.

## Notas por PC

- O `LSC_DADOS_DIR` do PC onde o marco 1 foi feito aponta para a pasta pCloud com a folha de
  ponto real (definido no `.env` local).
