# Instalação com servidor (várias pessoas, vários sítios)

Este guia põe o LSC Presenças a funcionar com uma base de dados única para o Grupo LSC, num PC
do escritório, usada por várias pessoas ao mesmo tempo, dentro e fora do escritório.

Quem só usa o programa num PC não precisa de nada disto: sem servidor, os dados ficam num
ficheiro desse PC e o programa funciona como sempre.

## Como fica montado

```
  PC do escritório (servidor)                 Outros PCs
  ┌─────────────────────────────┐             ┌──────────────────────────┐
  │ PostgreSQL                  │◄────rede────│ LSC-Presencas.exe        │
  │  base de dados lsc_presencas│   ou VPN    │  «Ligação ao servidor…»  │
  │ Cópia de segurança diária   │             └──────────────────────────┘
  └─────────────────────────────┘
```

- Os dados estão só no servidor. Os outros PCs não guardam nada, além das cópias de segurança
  que o administrador fizer à mão ou ao fechar um mês.
- Dentro do escritório, os PCs ligam-se pela rede. Fora do escritório, ligam-se por uma VPN.
- **O servidor nunca fica aberto diretamente à Internet.** Não se abre a porta 5432 no router.

## O que é preciso decidir antes

| Decisão | Recomendação |
|---|---|
| Que PC é o servidor | Um PC do escritório que esteja sempre ligado, com Windows 10 ou 11 e cabo de rede. Se estiver desligado, ninguém trabalha. |
| Endereço do servidor | Um endereço fixo na rede (reservado no router) ou o nome do PC. |
| VPN | A que o escritório já tiver. Se não houver nenhuma, ver o passo 4. |
| Quem sabe a palavra-passe do servidor | Só o administrador. Em cada PC, é ele que a escreve uma vez; fica guardada no cofre de credenciais do Windows desse utilizador. |
| Para onde vão as cópias de segurança | Outro disco do servidor e, de preferência, também para fora do edifício. |

## Passo 1 — Instalar o PostgreSQL no servidor

1. Descarregar o instalador para Windows em <https://www.postgresql.org/download/windows/>
   (versão 16 ou 17) e instalar com as opções por omissão.
2. Durante a instalação é pedida a palavra-passe do utilizador `postgres` (o administrador do
   servidor). Escolher uma forte e guardá-la num gestor de palavras-passe. Não é a que a app
   usa.
3. Manter a porta `5432`.

## Passo 2 — Criar a base de dados

1. Copiar para o servidor o ficheiro `scripts\servidor\criar_base_de_dados.sql`.
2. Abri-lo no Bloco de Notas e trocar `TROCAR_ESTA_PALAVRA_PASSE` por uma palavra-passe forte,
   só para a app.
3. Numa linha de comandos, na pasta onde está o ficheiro:

   ```
   "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -f criar_base_de_dados.sql
   ```

4. Apagar o ficheiro (ou voltar a pôr o texto original), para a palavra-passe não ficar lá.

**Em alternativa, pelo pgAdmin 4:** abrir `Databases`, botão direito em `postgres` → *Query Tool*,
abrir o ficheiro e trocar a palavra-passe. O pgAdmin corre o ficheiro inteiro numa só transação e
o `CREATE DATABASE` falha assim («cannot run inside a transaction block»): selecionar e executar
(F5) **uma instrução de cada vez** — primeiro o `CREATE ROLE`, depois o `CREATE DATABASE`, depois
o `REVOKE` e o `GRANT`. No fim, fechar sem guardar o ficheiro e limpar o *Query History*.

Fica criado o utilizador `lsc_app` e a base de dados `lsc_presencas`, vazia. As tabelas são
criadas pelo programa na primeira ligação.

## Passo 3 — Deixar os outros PCs ligarem-se

Por omissão, o PostgreSQL só aceita ligações do próprio PC. São três alterações no servidor.

**Forma rápida:** copiar `scripts\servidor\abrir_rede.cmd` para o servidor, ajustar no topo a
versão do PostgreSQL e a rede (por exemplo `192.168.1.0/24`) e corrê-lo com botão direito →
*Executar como administrador*, com o programa fechado. Faz os pontos 2, 3 e 4 abaixo, guarda uma
cópia do `pg_hba.conf` original e pode correr-se outra vez para outra rede (a da VPN).

À mão (nos caminhos, trocar `17` pela versão instalada):

1. **`postgresql.conf`** (em `C:\Program Files\PostgreSQL\17\data`): confirmar a linha

   ```
   listen_addresses = '*'
   ```

2. **`pg_hba.conf`** (na mesma pasta): acrescentar no fim uma linha por cada rede que pode
   entrar, só para esta base de dados e este utilizador. Trocar os endereços pelos verdadeiros:

   ```
   # rede do escritório
   host  lsc_presencas  lsc_app  192.168.1.0/24   scram-sha-256
   # rede da VPN
   host  lsc_presencas  lsc_app  100.64.0.0/10    scram-sha-256
   ```

   Não usar `0.0.0.0/0` nem `trust`.

3. **Firewall do Windows**: criar uma regra de entrada para a porta TCP 5432, limitada às
   mesmas redes (separador "Âmbito" da regra) e só nos perfis de rede privados.

4. Reiniciar o serviço `postgresql-x64-17` (em Serviços do Windows).

## Passo 4 — Acesso de fora do escritório (VPN)

Os PCs fora do escritório têm de chegar ao servidor como se estivessem lá dentro.

- **Se o escritório já tem VPN** (no router ou na firewall): usar essa. O endereço do
  servidor é o da rede do escritório.
- **Se não tem**: a opção com menos trabalho é uma VPN de malha, que se instala no servidor e
  em cada PC de fora e não obriga a mexer no router (por exemplo Tailscale ou ZeroTier). Cada
  PC fica com um endereço próprio dentro da VPN; o do servidor é o que se escreve no programa.
  A alternativa clássica é o WireGuard ou a VPN do próprio router.

Em qualquer caso: quem sai da empresa perde o acesso à VPN no mesmo dia, e a rede da VPN é uma
das que se autorizou no passo 3.

Com a VPN, a ligação ao servidor fica cifrada de ponta a ponta. Dentro do escritório, o
tráfego da base de dados circula na rede local.

## Passo 5 — Cópias de segurança no servidor

As cópias do servidor fazem-se no servidor, todos os dias, sem depender de ninguém.

1. Copiar `scripts\servidor\copia_seguranca.cmd` para o servidor (por exemplo para
   `C:\LSC-Servidor`) e ajustar as linhas do topo: a pasta do PostgreSQL, a pasta de
   destino (num disco do próprio servidor), quantos dias guardar e, em `COPIA_FORA`, uma
   segunda pasta para onde cada cópia também vai (outro disco, ou uma pasta sincronizada com a
   nuvem). A base de dados em si nunca se põe numa pasta sincronizada: só as cópias.
2. Para o `pg_dump` não pedir a palavra-passe, criar o ficheiro
   `%APPDATA%\postgresql\pgpass.conf` do utilizador que vai correr a tarefa (o
   `palavra_passe_das_copias.cmd` cria-o e abre-o no Bloco de Notas), com uma linha:

   ```
   localhost:5432:lsc_presencas:lsc_app:A_PALAVRA_PASSE_DA_APP
   ```

   Esse ficheiro só deve poder ser lido por esse utilizador.
3. No Agendador de Tarefas do Windows, criar uma tarefa diária (por exemplo às 22:00) que
   corre o `copia_seguranca.cmd`, com a opção "Executar quer o utilizador tenha sessão
   iniciada ou não". Se `COPIA_FORA` for uma unidade que só existe com a sessão iniciada
   (pCloud, Google Drive…), a tarefa tem de correr com a sessão iniciada, a uma hora em que o
   PC esteja em uso.
4. Correr a tarefa uma vez à mão e confirmar que apareceu um ficheiro `.dump` na pasta de
   destino e uma linha `OK` no `registo.txt`.
5. Copiar essa pasta regularmente para fora do edifício (disco externo ou nuvem). Uma cópia
   que está no mesmo PC não protege contra roubo, incêndio ou avaria do disco.

**Para repor uma cópia** (com o programa fechado em todos os PCs):

```
"C:\Program Files\PostgreSQL\17\bin\pg_restore.exe" -h localhost -U lsc_app -d lsc_presencas --clean --if-exists ficheiro.dump
```

Experimentar repor uma cópia pelo menos uma vez, numa base de dados de teste, antes de
precisar a sério.

Além destas, o programa descarrega uma cópia para o PC do administrador antes de fechar ou
reabrir um mês, e quando ele carrega em "Fazer uma cópia de segurança agora". Essas cópias são
ficheiros que o próprio programa sabe abrir.

## Passo 6 — Ligar o primeiro PC e enviar os dados

No PC onde estão os dados atuais (se houver):

1. Abrir o programa e entrar como administrador.
2. **Base de dados → Ligação ao servidor…**
3. Preencher o servidor (nome ou endereço), a porta `5432`, a base de dados `lsc_presencas`, o
   utilizador `lsc_app` e a palavra-passe da app.
4. **Testar a ligação.** O programa cria as tabelas no servidor e diz o que encontrou.
5. Se o servidor estiver vazio e este PC tiver dados, aparece a opção **"Enviar para o
   servidor os dados que estão neste PC"**, já marcada. Vão as empresas, os trabalhadores, as
   marcações, os fechos, a auditoria e as contas de login.
6. **Guardar e usar o servidor.** O programa fecha; ao abrir outra vez, já trabalha no
   servidor, com as mesmas contas.

O ficheiro antigo fica no PC, intacto, mas deixa de ser usado. O programa nunca escreve por
cima de um servidor que já tenha dados.

## Passo 7 — Ligar os outros PCs

1. Copiar a pasta `LSC-Presencas` (a do executável) para o PC.
2. Abrir o programa. No ecrã de entrada, carregar em **Ligação ao servidor…**, preencher e
   guardar. O programa fecha.
3. Abrir outra vez: aparece o login, com as contas que existem no servidor.

Fora do escritório, ligar primeiro a VPN.

## Atualizar o programa

Uma versão nova pode mudar a estrutura da base de dados. Ao abrir, a versão nova atualiza o
servidor sozinha. A partir daí, um PC com a versão antiga recebe o aviso "a base de dados do
servidor é de uma versão mais recente" e não entra até ser atualizado.

Por isso: atualizar todos os PCs no mesmo dia, com o programa fechado em todos, e depois de
uma cópia de segurança.

## Como o programa se comporta com várias pessoas

- A grelha de presenças vai buscar as alterações dos outros de 15 em 15 segundos, e na hora
  com **Atualizar (F5)**.
- Se duas pessoas mexerem na mesma célula, a segunda recebe um aviso, vê o valor da primeira e
  não grava nada por cima sem o ter visto.
- Enquanto um administrador fecha um mês, as gravações dos outros esperam uns segundos. Depois
  do fecho, quem ainda via o mês aberto é avisado quando tentar gravar.
- **Cadeado:** enquanto uma pessoa tem a ficha de um funcionário aberta, ou células dele
  selecionadas na grelha, esse funcionário aparece aos outros com um cadeado e fica só de
  leitura (presenças, lançamentos e ficha). Passar o rato por cima diz quem o tem. O cadeado
  sai quando a pessoa fecha a ficha, muda a seleção, muda de ecrã ou fecha o programa. Os
  outros veem a mudança na atualização seguinte (até 15 segundos, ou F5). Se o programa
  fechar mal ou a rede cair, o cadeado sai sozinho ao fim de 90 segundos.
- Nas tabelas (clientes, viaturas, parâmetros…), se dois administradores alterarem o mesmo
  registo, fica a última gravação.

## Problemas comuns

| O que aparece | O que ver |
|---|---|
| "Não foi possível chegar ao servidor" | O servidor está ligado? A VPN está ligada? O endereço e a porta estão certos? A firewall do servidor deixa entrar essa rede? |
| "O servidor recusou o utilizador ou a palavra-passe" | A palavra-passe da app (não a do `postgres`). A rede desse PC está no `pg_hba.conf`? |
| "Essa base de dados não existe no servidor" | O passo 2 foi feito? O nome está bem escrito? |
| "A base de dados do servidor é de uma versão mais recente" | Atualizar o programa nesse PC. |
| O administrador esqueceu-se da palavra-passe do programa | Num PC ligado ao servidor: `LSC-Presencas.exe repor-admin` (por exemplo num atalho com esse argumento). Fica registado na auditoria. |
| Um PC deve deixar de ter acesso | Tirar-lhe a VPN. Se a palavra-passe da app tiver sido vista por quem não devia, mudá-la no servidor (`ALTER ROLE lsc_app PASSWORD '...'`) e voltar a escrevê-la em cada PC. |

## O que o login protege e o que não protege

O login e os perfis controlam o que cada pessoa faz dentro do programa, e põem o nome dela na
auditoria. Não são uma barreira contra quem tenha a palavra-passe do servidor: com ela e com
acesso à rede, chega-se aos dados por fora do programa. Por isso a palavra-passe do servidor
fica só com o administrador, a rede autorizada é só a do escritório e a da VPN, e o servidor
está num sítio físico de acesso controlado.
