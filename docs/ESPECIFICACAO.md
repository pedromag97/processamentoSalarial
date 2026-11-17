# Especificação — App de Presenças e Pré-processamento Salarial (Groupe LSC)

> Este é o prompt original do Pedro (2026-11-17). Duas alterações feitas depois: o repositório
> chama-se `processamentoSalarial` (e não `lsc-presencas`), e o Excel real chama-se
> `2027  Folha de PONTO Semanal v2027.xlsx`. As decisões tomadas a partir daqui estão no
> `CLAUDE.md` e no `PROGRESSO.md`.

---

## 0. Como quero que trabalhes

1. **Não escrevas código já.** Começa por ler este documento e o ficheiro Excel (`Folha_de_PONTO_Semanal_v2027.xlsx`, folha `s-27`). Depois apresenta-me um plano de implementação por marcos e uma lista das dúvidas que ficaram. Só avanças depois de eu aprovar.
2. Trabalha por marcos (secção 9). No fim de cada marco: os testes passam, a app arranca e mostras-me o que mudou.
3. Toda a lógica de cálculo fica num módulo puro (sem interface), com testes `pytest`. A interface só chama esse módulo.
4. Todos os valores monetários, taxas e limites ficam em **tabelas de configuração editáveis na app**, nunca em código. Quando eu não te dei um valor, deixa um campo vazio e um aviso no ecrã; não inventes valores legais.
5. A interface, as mensagens e o código de domínio (nomes de tabelas, por exemplo) ficam em português de Portugal.

## 0.1 Desenvolvimento em 2 PCs (obrigatório desde o primeiro commit)

Desenvolvo este projeto com o Claude Code em **dois PCs Windows**. Tenho de conseguir parar num PC e continuar no outro sem perder contexto.

1. **Repositório Git privado no GitHub** (conta `pedromag97`, repo `lsc-presencas`). Cria-o com `gh repo create --private` se o `gh` estiver disponível; se não estiver, dá-me os comandos.
2. **Ritual de início de sessão** (escreve-o no `CLAUDE.md`):
   - `git pull`;
   - instalar ou atualizar as dependências (`uv sync` ou `pip install -r requirements.txt` no venv);
   - correr as migrações e os testes;
   - ler o `PROGRESSO.md` e dizer-me em 3 linhas onde ficámos e qual é o próximo passo.
3. **Ritual de fim de sessão:**
   - testes a passar;
   - atualizar o `PROGRESSO.md`;
   - commit com uma mensagem clara;
   - `git push`.
   - Se o trabalho ficar a meio, faz commit à mesma num branch `wip/<tema>` e escreve no `PROGRESSO.md` o que falta. Nunca deixes trabalho só local.
4. **`CLAUDE.md`** na raiz, com o resumo deste prompt: decisões tomadas, stack, convenções, comandos e os rituais acima. É a memória do projeto: o Claude Code de qualquer um dos PCs lê-o automaticamente. Mantém-no atualizado quando uma decisão mudar.
5. **`PROGRESSO.md`**, com:
   - o marco atual;
   - uma checklist das tarefas;
   - as decisões tomadas e a data;
   - as dúvidas em aberto;
   - "próximo passo" numa frase.
   Este documento (o prompt) fica em `docs/ESPECIFICACAO.md`.
6. **Ambiente reproduzível:**
   - versões fixas das dependências (`uv.lock` ou `requirements.txt` com versões);
   - `.python-version`;
   - um script `setup.ps1` que, num PC novo, cria o venv, instala tudo, corre as migrações e carrega os dados de demonstração;
   - nada de caminhos absolutos no código; os caminhos vêm de `config` / variáveis de ambiente.
7. **Fora do Git** (`.gitignore`):
   - o venv, a base de dados SQLite, os backups, os PDF/Excel gerados e o `.env`;
   - **o Excel original e qualquer dado real dos trabalhadores**, porque são dados pessoais. Para desenvolver e testar usa um **seed de demonstração** com nomes fictícios (`scripts/seed_demo.py`), igual nos dois PCs.
   - O Excel real fica numa pasta local indicada por `LSC_DADOS_DIR` no `.env` (há um `.env.example` no repo).
   - Para os testes da importação, cria um **Excel fictício com a mesma estrutura da `s-27`** em `tests/fixtures/`.

## 1. Contexto do negócio

- Grupo familiar (Groupe LSC) com duas empresas empregadoras: **LOUSACABO CONSTRUÇÕES LDA** e **+INNOVATION**. Cerca de 70 trabalhadores, a maioria em obras de fibra ótica (FTTH) em **França**.
- Os trabalhadores têm **contrato português e estão destacados em França**. O recibo final é português e é emitido pelo contabilista no software salarial dele.
- **O que esta app faz:** marcação diária de presenças num dashboard global e **pré-processamento salarial mensal** (dias, faltas, subsídios, ajudas de custo, horas extra, prevenção, adiantamentos e descontos). Gera um PDF por trabalhador e um Excel-resumo por empresa, que seguem para o contabilista.
- **O que esta app NÃO faz:** não calcula a retenção de IRS, não calcula a TSU, não calcula o líquido final nem emite o recibo oficial. O PDF tem de dizer claramente "Mapa de pré-processamento — não substitui o recibo de vencimento".
- Só o escritório usa a app (1–2 pessoas, um PC Windows). Não há login multiutilizador nem acesso remoto.

## 2. Stack técnica

- Python 3.12, **PySide6** (desktop Windows), **SQLite** com SQLAlchemy 2.x e migrações Alembic.
- `openpyxl` para importar e exportar Excel; `reportlab` para os PDF.
- Empacotamento com **PyInstaller** (pasta com `.exe`), com a base de dados numa pasta de dados do utilizador (`%APPDATA%/LSC-Presencas/`).
- **Backup automático** da base de dados ao abrir a app e antes de cada fecho de mês (manter os últimos 30).
- `pytest` para os testes; `ruff` para o lint.

## 3. Modelo de dados (mínimo; propõe melhorias)

- **Empresa**: nome, NIPC, morada, logótipo (opcional).
- **Cliente**: código (ex.: `drp+`, `drp++`, `GG`, `FD`, `BA`, `rm`, `cgo`), nome completo.
- **Viatura**: código/matrícula curta (ex.: `ZC`, `BR`, `AD 81`, `TS`), descrição.
- **Obra/Zona**: nome (ex.: `45 Orleans`, `64 Biarritz`), país.
- **Trabalhador**: nº interno, nome, empresa, cliente atual, viatura atual, zona atual, data de admissão e de saída, salário base mensal, ativo (sim/não), e os **valores de exceção** (subsídio de alimentação, ajuda de custo França, prevenção, valor/hora extra). Um campo vazio significa que usa o valor global da empresa.
- **CódigoPresença** (tabela editável, secção 4).
- **Marcação**: trabalhador, data, código, horas extra (decimal, 0 por defeito), cliente, viatura, zona (copiados da ficha do trabalhador no momento da marcação e editáveis), nota. Chave única: (trabalhador, data).
- **Feriado**: data, nome, tipo (nacional/municipal). Carregar os feriados nacionais de Portugal de 2026 e 2027.
- **Lançamento manual**: trabalhador, mês, tipo (adiantamento, desconto, prémio, outro), descrição, valor (+/−).
- **ParâmetrosEmpresa** (por empresa e com data de início de vigência): subsídio de alimentação por dia, ajuda de custo França por dia, valor por dia de prevenção, horas semanais (40), acréscimos de horas extra, limites de isenção fiscal do subsídio e da ajuda de custo (vazios até eu os preencher com o contabilista).
- **FechoMês**: empresa, ano, mês, estado (aberto/fechado), data, utilizador e nota. Mês fechado = marcações só de leitura. Reabrir obriga a um motivo, que fica registado.
- **Auditoria**: qualquer alteração a uma marcação ou lançamento grava quem, quando, o valor antigo e o novo.

## 4. Códigos de presença (aceites)

| Código | Significado | Conta como trabalhado | Subsídio alimentação | Ajuda custo França | Desconta salário base |
|---|---|---|---|---|---|
| P | Presente em Portugal | sim | sim | não | não |
| PF | Presente em França | sim | configurável* | sim | não |
| DF | Deslocado em França sem trabalhar (fim de semana, espera) | não | não | sim | não |
| FE | Férias | não | não | não | não |
| FER | Feriado | não | não | não | não |
| FJ | Falta justificada | não | não | não | configurável (por defeito não) |
| FI | Falta injustificada | não | não | não | **sim** |
| B | Baixa por doença | não | não | não | **sim** |
| AT | Acidente de trabalho | não | não | não | **sim** |
| PR | Prevenção | sim | sim | conforme zona | não; soma o valor de prevenção |

\* Flag "PF acumula subsídio de alimentação com a ajuda de custo": por defeito **não**; tem de ser confirmada com o contabilista.

- Estas colunas são **atributos editáveis** da tabela `CódigoPresença` (cor, abreviatura, flags). Posso criar códigos novos sem mexer no código.
- **Horas extra:** na célula escreve-se `P+2` ou `PF+1.5`, que quer dizer código + horas extra desse dia. A grelha mostra o código e um pequeno indicador das horas.

## 5. Regras de cálculo do pré-processamento (mês civil, por trabalhador)

Todas as fórmulas ficam num módulo `calculo.py`, testado caso a caso. Sempre que uma regra dependa de lei ou de contrato coletivo, o valor vem dos parâmetros e o PDF mostra a fórmula usada.

1. **Contagens:** dias por código no mês, considerando só o período entre a admissão e a saída.
2. **Salário base processado:** base − (base / 30 × dias com flag "desconta salário base"). Se o trabalhador entrou ou saiu a meio do mês, proporcional (base / 30 × dias de contrato). O divisor 30 fica configurável.
3. **Subsídio de alimentação:** nº de dias com a flag × valor do dia (exceção do trabalhador ou valor global). Separar a parte isenta da parte sujeita segundo o limite configurado; se o limite estiver vazio, mostrar só o total e um aviso.
4. **Ajuda de custo França:** nº de dias PF + DF × valor do dia. Separar também a parte isenta da sujeita, como no ponto 3.
5. **Prevenção:** nº de dias PR × valor do dia.
6. **Horas extra:**
   - Valor/hora = (base × 12) / (52 × horas semanais).
   - Acréscimos por defeito (editáveis): dia útil, 1.ª hora +25% e horas seguintes +37,5%; dia de descanso ou feriado (sábado, domingo ou um dia da tabela de feriados) +50%.
   - Mostrar as horas e o valor por tipo de acréscimo.
7. **Lançamentos manuais:** somam ou subtraem, com a descrição.
8. **Total ilíquido estimado** = soma das rubricas acima. Mostrado com a etiqueta "estimado, antes de IRS e TSU".
9. **Validações e alertas** no ecrã de fecho:
   - dias úteis sem marcação;
   - marcação em dia de feriado com código P/PF (pedir confirmação);
   - trabalhador ativo sem salário base;
   - parâmetros em falta;
   - marcações depois da data de saída;
   - total de horas extra no mês acima de um limite configurável.

## 6. Ecrãs

1. **Dashboard de presenças (ecrã principal)**
   - Grelha: linhas = trabalhadores agrupados por **Empresa → Cliente** (grupos recolhíveis); colunas = dias do mês, com o dia da semana. Vista **mensal** (por defeito) e vista **semanal**, igual à folha de ponto atual.
   - Fins de semana e feriados sombreados; cada código com a sua cor.
   - Edição rápida por teclado: escrever o código na célula, setas e Enter para navegar, **copiar/colar intervalos**, selecionar um intervalo e aplicar um código (ex.: semana inteira PF), e Ctrl+Z.
   - Colunas fixas à esquerda: nº, nome, cliente, viatura. Colunas de totais à direita: P, PF, DF, FE, FI, B, horas extra.
   - Filtros por empresa, cliente, viatura, zona e ativo/inativo. Pesquisa por nome.
   - Linha de totais por dia (quantas pessoas presentes, por cliente).
   - Botão "Copiar semana anterior" para a semana selecionada.
2. **Trabalhadores:** lista e ficha (dados, empresa, cliente, viatura, valores de exceção, histórico).
3. **Tabelas:** empresas, clientes, viaturas, zonas, códigos de presença, feriados e parâmetros por empresa (com vigência).
4. **Lançamentos manuais** por mês.
5. **Fecho do mês** por empresa: lista de alertas, pré-visualização dos totais por trabalhador, botão Fechar, e exportação (PDF e Excel).
6. **Relatórios:**
   - mapa anual de férias por trabalhador (substitui as folhas `ferias27` e `P,Ferias`);
   - dias por cliente e por viatura no mês (útil para a faturação e os custos);
   - mapa de prevenção (substitui `Prev`).

## 7. Saídas

- **PDF por trabalhador** (um ficheiro por pessoa e um PDF juntando todos, por empresa):
  - cabeçalho com a empresa, o trabalhador, o mês e o cliente/zona principal;
  - mini-calendário do mês com os códigos;
  - tabela de rubricas (quantidade, valor unitário, total, isento/sujeito);
  - lançamentos manuais e o total ilíquido estimado;
  - aviso legal no rodapé: "Mapa de pré-processamento — não substitui o recibo de vencimento";
  - espaço para a assinatura do trabalhador.
- **Excel resumo mensal por empresa:** uma linha por trabalhador, uma coluna por rubrica (dias por código, subsídio isento e sujeito, ajuda de custo isenta e sujeita, prevenção, horas extra por acréscimo, adiantamentos, descontos, base processada, total). Mais uma folha com o detalhe diário das marcações e uma folha com os parâmetros usados nesse mês.
- Nome dos ficheiros: `AAAA-MM_<EMPRESA>_resumo.xlsx` e `AAAA-MM_<EMPRESA>_<nº>_<nome>.pdf`.

## 8. Importação única da folha `s-27` (migração)

A app passa a ser a fonte única de dados; o Excel é importado **uma vez**, por um assistente com pré-visualização antes de gravar.

Estrutura real da folha `s-27`:
- **Bloco 1:** linhas 7 a 46. Cabeçalhos nas linhas 2 (ano), 3 (mês), 4 (nº da semana), 5 (dia do mês) e 6 (dia da semana).
- **Bloco 2:** linhas 55 a 78, com cabeçalhos repetidos nas linhas 50 a 54. As linhas 65 (`45 Orleans`) e 68 (`64 Biarritz`) são **títulos de zona** e não trabalhadores: os trabalhadores abaixo de cada título pertencem a essa zona até ao título seguinte.
- **Colunas:** A = nº, B = nº dentro do grupo, **C = cliente**, **D = viatura**, E = nome. Os dias começam na **coluna K = segunda-feira, 28/12/2026**, e cada coluna seguinte é +1 dia, até à coluna NQ.
- **Atenção:** a linha 5 tem números de dia errados em vários sítios (ex.: `EJ5`, `EM5`, `ET5`). **Calcula a data pela posição da coluna** e não pela linha 5. Regista as discrepâncias num relatório de importação.
- Há linhas com nome vazio, mas com viatura (ex.: linhas 70, 77 e 78). Importa a viatura para a tabela de viaturas e ignora a linha como trabalhador.
- Há **nomes duplicados** entre os blocos. Mostra um ecrã para eu decidir se é a mesma pessoa ou outra, comparando sem distinguir maiúsculas nem acentos.
- **Códigos antigos** a mapear (mostra o mapeamento num ecrã para eu confirmar antes de gravar): `x` → P, `ferias` → FE, `falta` → FI, `baixa` e `b` → B, `s` → **perguntar-me**. Qualquer outro valor encontrado nas células de dias aparece listado para eu mapear.
- A empresa de cada trabalhador não está na `s-27`. Depois da importação, mostra a lista para eu atribuir a empresa em massa (seleção múltipla). A folha `FM` (colunas AF "Lousa" e AG "Lusoc") pode ajudar a sugerir a empresa.

## 9. Marcos

1. Repositório Git + `CLAUDE.md` + `PROGRESSO.md` + `setup.ps1` + seed de demonstração (secção 0.1). Depois, estrutura do projeto, modelo de dados, migrações, carregamento de feriados e códigos, e testes do modelo.
2. Módulo `calculo.py` completo, com testes que cubram todos os códigos, a admissão/saída a meio do mês, as horas extra em dia útil, fim de semana e feriado, os limites de isenção vazios e preenchidos, e as exceções por trabalhador.
3. Ecrãs de tabelas e trabalhadores.
4. Dashboard de presenças (grelha, edição por teclado, colar intervalos, filtros, totais e desfazer).
5. Importação da `s-27` com pré-visualização e relatório.
6. Fecho do mês, alertas, exportação para Excel e PDF.
7. Relatórios (férias, clientes/viaturas, prevenção), backups, auditoria e empacotamento PyInstaller.

**Critérios de aceitação:**
- marcar um mês inteiro para 70 trabalhadores leva menos de 10 minutos com copiar/colar;
- a grelha abre em menos de 1 segundo com 80 trabalhadores × 31 dias;
- os totais do Excel batem certo com a soma dos PDF;
- um mês fechado não pode ser editado sem reabertura registada.

## 10. Pontos ainda em aberto (pergunta-me antes do marco 2)

- Valores do subsídio de alimentação, da ajuda de custo França e da prevenção por empresa.
- Limites de isenção fiscal em vigor (a confirmar com o contabilista).
- Se PF acumula o subsídio de alimentação.
- Se FJ desconta o salário.
- O significado do código antigo `s`.
- Se há contrato coletivo aplicável que altere os acréscimos de horas extra.
- Como se trata a baixa por acidente de trabalho (AT): é paga pela seguradora, mas deve aparecer no mapa.
