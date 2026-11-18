# Progresso

## Marco atual

**Marco 9 concluído** (2026-11-18): a app funciona sobre um servidor PostgreSQL. À espera da
aprovação do Pedro para o marco 10.

Os sete marcos da especificação original estão feitos (versão 1.0.0). A 2026-11-18 o Pedro
pediu contas de login e uma base de dados única do Grupo LSC, usada por várias pessoas ao
mesmo tempo e em sítios diferentes. Aprovou o plano dos marcos 8 a 11 (abaixo).

A importação real ainda **não foi feita**: só se ensaiou a leitura do Excel real (sem gravar).
Fica para o Pedro a fazer no PC do escritório, pelo assistente.

O cálculo (marco 2) foi feito com pressupostos (lista abaixo) que o Pedro mandou assumir; falta
confirmá-los com o contabilista.

## Próximo passo

Marco 10: uso em simultâneo. A grelha tem de mostrar o que os outros marcam, duas pessoas na
mesma célula não se podem atropelar sem aviso, o fecho tem de ser seguro com outros ligados,
e a sessão da interface não pode ficar com uma transação aberta durante horas.

Em paralelo, o Pedro experimenta a app com dados reais (importação da `s-27`, valores com o
contabilista, um mês completo, fecho e ficheiros).

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
- [x] Ficha: histórico de alterações (feito no marco 7, com a auditoria)

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

### Marco 6 — fecho do mês, alertas, Excel e PDF
- [x] Migração `0002`: fotografia do fecho (`fecho_mes.fotografia` e tabela `fecho_trabalhador`)
- [x] `mapa.py`: o mapa do mês de uma empresa (o mesmo objeto para o ecrã, o Excel e os PDF)
- [x] `fecho.py`: alertas, fechar (recusa com erros, pede confirmação dos avisos), reabrir com
      motivo obrigatório; tudo registado na auditoria
- [x] `backups.py`: cópia de segurança antes de fechar e antes de reabrir (ficam as últimas 30)
- [x] `lancamentos.py` e ecrã «Lançamentos»: por mês, com auditoria e bloqueio do mês fechado
- [x] Ecrã «Fecho do mês»: alertas, totais por trabalhador, Fechar, Reabrir, Exportar
- [x] Excel-resumo (`Resumo`, `Marcações`, `Parâmetros`) e PDF por trabalhador + PDF conjunto,
      em `saidas\AAAA-MM_<EMPRESA>\` na pasta da app
- [x] Teste do critério "os totais do Excel batem certo com a soma dos PDF" (lê os PDF gerados)
- [ ] Por ver pelo Pedro: o aspeto do PDF e as colunas do Excel-resumo

### Marco 7 — relatórios, backups, auditoria e empacotamento
- [x] `relatorios.py` e ecrã «Relatórios»: mapa anual de férias, mapa anual de prevenção, dias
      por cliente e dias por viatura no mês; exportação para Excel em `saidas\relatorios\`
- [x] `auditoria.py` e ecrã «Auditoria» (filtro por tipo e pesquisa; 500 registos mais recentes)
- [x] Ficha do trabalhador: separador «Histórico de alterações»; as alterações à ficha e ao
      salário base passam a ficar na auditoria
- [x] Cópia de segurança ao abrir a app (antes das migrações); botão para fazer uma cópia e
      abrir a pasta, no ecrã «Base de dados»
- [x] `scripts\empacotar.cmd` (PyInstaller): pasta com `LSC-Presencas.exe`, testada (migra,
      abre a janela e faz a cópia ao abrir)
- [ ] Por fazer pelo Pedro: copiar a pasta do executável para o PC do escritório e experimentar

### Depois do marco 7 (pedidos do Pedro a 2026-11-18)
- [x] Grelha: colunas fixas redimensionáveis (a largura fica guardada em `interface.json`)
- [x] Grelha: explicações ao passar o rato (botões de código, células, cabeçalhos, grupos)

### Marco 8 — contas e login
- [x] Tabela `utilizador` (migração `0003`); palavra-passe guardada só como resumo scrypt
- [x] `contas.py`: criar, autenticar (bloqueio de 5 min após 5 falhas), perfis, sessão em curso
- [x] Ao abrir: criar o primeiro administrador ou pedir o login; "Terminar sessão" e "Mudar a
      palavra-passe" na barra lateral
- [x] Ecrã «Contas» (só administrador): criar, repor a palavra-passe, mudar o perfil,
      ativar/desativar; tem de ficar sempre um administrador ativo
- [x] Permissões: o utilizador não altera tabelas, fichas nem salários, não fecha nem reabre
      meses, não importa, e não vê os ecrãs Contas, Auditoria e Base de dados
- [x] A auditoria passa a registar o nome da conta (em vez do utilizador do Windows)
- [x] Recuperação: `LSC-Presencas.exe repor-admin` (ou `python -m lsc_presencas repor-admin`)

### Marco 9 — base de dados em servidor
- [x] Ligação configurável: `LSC_BD_URL` (desenvolvimento), ou `ligacao.json` na pasta da app
      com a palavra-passe no cofre de credenciais do Windows, ou o ficheiro local
- [x] As três migrações e todo o cálculo/fecho/exportação testados em PostgreSQL 16
      (servidor de teste do pacote `pgserver`, arrancado pelos próprios testes)
- [x] `transferencia.py`: copia todos os dados entre bases de dados, preservando os ids
- [x] `servidor.py` e diálogo «Ligação ao servidor» (no login, no ecrã Base de dados e quando
      o servidor não responde ao abrir): testar, guardar, enviar os dados deste PC para um
      servidor vazio, voltar ao ficheiro local
- [x] Cópias de segurança com servidor: descarregam tudo para um ficheiro SQLite local (antes
      de fechar/reabrir um mês e à mão); não há cópia ao abrir
- [x] Mensagens de erro do PostgreSQL e de falha de rede em português
- [ ] Por fazer no marco 11: instalar o servidor verdadeiro, a VPN e a cópia agendada no servidor

### Marcos seguintes (plano aprovado a 2026-11-18)
- [ ] 10 — Uso em simultâneo: a grelha atualiza-se, conflitos na mesma célula, fecho seguro
- [ ] 11 — Instalação: guia do servidor e da VPN, executável novo, teste entre dois PCs

### Por validar pelo Pedro (critérios de aceitação)
- [ ] Marcar um mês para 70 trabalhadores em menos de 10 minutos
- [ ] Aspeto do PDF e colunas do Excel-resumo
- [ ] Pressupostos do cálculo e valores, com o contabilista

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
| 2026-11-18 | Fecho: erros impedem fechar; avisos pedem um visto de confirmação. Reabrir apaga a fotografia (fica no backup feito antes). |
| 2026-11-18 | Um mês aberto pode ser exportado, mas os ficheiros saem marcados "PROVISÓRIO" e numa pasta própria. |
| 2026-11-18 | Entram no fecho de uma empresa os trabalhadores ativos com contrato no mês e quem tiver marcações ou lançamentos nesse mês. |

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

### Do fecho (assumido em 2026-11-18)
- Adiantamentos e descontos escrevem-se com sinal menos; o ecrã avisa se estiverem positivos.
  Preferes que a app troque o sinal sozinha?
- O PDF não mostra os alertas do trabalhador (só a nota de rubricas por calcular). Está bem?
- Trabalhadores sem empresa não entram em nenhum fecho (há um aviso no ecrã).

### Das contas e do servidor (2026-11-18)
- Respostas do Pedro: dois perfis (administrador e utilizador); duas ou mais pessoas em
  simultâneo; um PC do escritório como servidor; PCs em sítios diferentes; o administrador
  repõe palavras-passe; sem bloqueio automático por inatividade; uma base de dados única
  para o Grupo LSC, com as várias empresas.
- Por confirmar: a tabela de permissões (o utilizador vê salários? pode alterar fichas?).
- Por saber: se já há VPN ou alguém que trate da informática do escritório. O servidor não
  deve ficar exposto diretamente à Internet.
- O login controla o uso da app; quem tiver as credenciais do servidor de base de dados
  chega aos dados por fora. Essas credenciais ficam só com o administrador.

### Dos relatórios (assumido em 2026-11-18)
- Férias = código `FE`; prevenção = códigos com a flag "soma prevenção".
- Dias por cliente/viatura contam só os códigos que "contam como trabalhado", pelo cliente e
  pela viatura gravados em cada marcação (não pelos da ficha atual).
- O mapa de férias não tem dias de direito nem saldo (a app não sabe quantos dias cada um tem).

### Outras
- Um trabalhador pode mudar de empresa a meio do ano? (Hoje o fecho usa a empresa atual.)
- Fins de semana sem marcação geram alerta ou são normais?
- O código antigo `s` não aparece na folha de 2027; só interessa se se importarem anos anteriores.

## Notas por PC

- O `LSC_DADOS_DIR` do PC onde o marco 1 foi feito aponta para a pasta pCloud com a folha de
  ponto real (definido no `.env` local).
