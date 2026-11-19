-- Cria o utilizador e a base de dados do LSC Presenças num servidor PostgreSQL.
--
-- Correr UMA vez, no PC servidor, como administrador do PostgreSQL (utilizador "postgres"):
--
--     psql -U postgres -f criar_base_de_dados.sql
--
-- No pgAdmin (Query Tool): selecionar e executar (F5) UMA instrução de cada vez. Tudo de
-- seguida falha com «CREATE DATABASE cannot run inside a transaction block».
--
-- ANTES de correr: troca TROCAR_ESTA_PALAVRA_PASSE por uma palavra-passe forte, só para a app.
-- É essa palavra-passe (e o utilizador lsc_app) que se escreve em «Ligação ao servidor…».
-- Não a guardes neste ficheiro depois de o correr.
--
-- As tabelas não se criam aqui: é o próprio programa que as cria na primeira ligação.

CREATE ROLE lsc_app LOGIN PASSWORD 'TROCAR_ESTA_PALAVRA_PASSE';

CREATE DATABASE lsc_presencas
    OWNER lsc_app
    ENCODING 'UTF8'
    TEMPLATE template0;

-- Só a app (e o administrador do servidor) se liga a esta base de dados.
REVOKE ALL ON DATABASE lsc_presencas FROM PUBLIC;
GRANT ALL ON DATABASE lsc_presencas TO lsc_app;
