# Progresso

## Marco atual

**Marco 1 concluído** (2026-11-17), à espera da aprovação do Pedro para começar o marco 2.

## Próximo passo

Obter do Pedro as respostas às dúvidas que bloqueiam o marco 2 (lista abaixo) e escrever o
`calculo.py` com os testes.

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
- [ ] Contagens por código, respeitando admissão e saída
- [ ] Salário base processado (descontos e proporcional)
- [ ] Subsídio de alimentação e ajuda de custo França (isento/sujeito, limite vazio ou preenchido)
- [ ] Prevenção
- [ ] Horas extra (dia útil, descanso, feriado)
- [ ] Lançamentos manuais e total ilíquido estimado
- [ ] Validações e alertas

### Marcos seguintes
- [ ] 3 — Ecrãs de tabelas e trabalhadores
- [ ] 4 — Dashboard de presenças
- [ ] 5 — Importação da `s-27` (inclui o Excel fictício em `tests/fixtures/`)
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

## Dúvidas em aberto

### Bloqueiam o marco 2 (regras de cálculo)
1. PR "conforme zona": dá ajuda de custo quando a zona da marcação é em França?
2. Proporcional de entrada/saída: dias de calendário de contrato ÷ 30, com teto no salário base?
3. Feriados: quem trabalha em França num feriado português tem +50% nas horas extra? E os
   feriados franceses contam?
4. Os limites de isenção são valores por dia (subsídio e ajuda de custo)?
5. Horas extra em dia útil: a "1.ª hora" é por dia?
6. Se PF acumula o subsídio de alimentação (por defeito: não).
7. Se FJ desconta o salário (por defeito: não).
8. Como tratar o AT: é pago pela seguradora, mas deve aparecer no mapa.
9. Há contrato coletivo que altere os acréscimos de horas extra?

### Não bloqueiam (valores a preencher na app)
- Subsídio de alimentação, ajuda de custo França e prevenção, por empresa.
- Limites de isenção fiscal (com o contabilista).

### Para o marco 5 (importação)
- "Lusoc" é a +INNOVATION ou uma terceira empresa?
- Posso usar os ficheiros `2027-LOUSA --Mapa de Ferias PT.xlsm` e
  `2027-LUSOC --Mapa de Ferias PT.xlsm` para sugerir a empresa de cada trabalhador?
- Um trabalhador pode mudar de empresa a meio do ano?
- Fins de semana sem marcação geram alerta ou são normais?
- O código antigo `s` não aparece na folha de 2027; só interessa se se importarem anos anteriores.

## Notas por PC

- O `LSC_DADOS_DIR` do PC onde o marco 1 foi feito aponta para a pasta pCloud com a folha de
  ponto real (definido no `.env` local).
