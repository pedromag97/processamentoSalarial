"""Passar a usar um servidor PostgreSQL: testar a ligação, preparar o servidor e, se for a
primeira vez, enviar para lá os dados que estão no ficheiro deste PC.

Sem interface. O ecrã está em ui/ecra_ligacao.py.
"""

from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError

from . import config, contas, db, transferencia


class ErroDeLigacao(ValueError):
    """Não foi possível ligar ao servidor (mensagem para mostrar ao utilizador)."""


@dataclass(frozen=True)
class Situacao:
    servidor_tem_dados: bool
    local_tem_dados: bool


def explicar(erro: Exception) -> str:
    """A mensagem do controlador, em português e sem a palavra-passe."""
    texto = str(getattr(erro, "orig", erro)).lower()
    if "password authentication failed" in texto or "no password supplied" in texto:
        return "O servidor recusou o utilizador ou a palavra-passe."
    if "does not exist" in texto and "database" in texto:
        return "Essa base de dados não existe no servidor."
    if "role" in texto and "does not exist" in texto:
        return "Esse utilizador não existe no servidor."
    if "can't locate revision" in texto:
        return (
            "A base de dados do servidor é de uma versão mais recente do programa. "
            "Atualize o programa neste PC."
        )
    if any(
        x in texto
        for x in (
            "timeout",
            "timed out",
            "refused",
            "could not translate",
            "unreachable",
            "getaddrinfo",
            "no route",
            "connection failed",
            "could not connect",
        )
    ):
        return (
            "Não foi possível chegar ao servidor. Confirme o nome ou endereço, a porta, e se "
            "a rede (ou a VPN) está ligada."
        )
    return f"Não foi possível ligar ao servidor: {str(getattr(erro, 'orig', erro)).strip()}"


def _local_tem_dados() -> bool:
    if not config.caminho_bd().is_file():
        return False
    db.migrar(config.url_local())
    local = db.criar_engine(config.url_local())
    try:
        return transferencia.tem_dados(local)
    finally:
        local.dispose()


def verificar(ligacao: config.Ligacao, senha: str) -> Situacao:
    """Testa a ligação, cria ou atualiza as tabelas no servidor e diz o que há em cada lado."""
    url = config.url_servidor(ligacao, senha)
    try:
        db.testar_ligacao(url)
        db.migrar(url)
        engine = db.criar_engine(url)
        try:
            servidor_tem_dados = transferencia.tem_dados(engine)
        finally:
            engine.dispose()
    except SQLAlchemyError as erro:
        raise ErroDeLigacao(explicar(erro)) from None
    except Exception as erro:  # noqa: BLE001 - ex.: erro do Alembic com uma versão mais nova
        raise ErroDeLigacao(explicar(erro)) from None
    return Situacao(servidor_tem_dados, _local_tem_dados())


def ligar(
    ligacao: config.Ligacao, senha: str, *, enviar_dados_locais: bool = False
) -> transferencia.Resultado | None:
    """Guarda a ligação neste PC. Com `enviar_dados_locais`, copia primeiro os dados do
    ficheiro local para o servidor, que tem de estar vazio (nunca se substituem dados do
    servidor). O ficheiro local fica como está.
    """
    situacao = verificar(ligacao, senha)
    resultado = None
    if enviar_dados_locais:
        contas.exigir_admin("enviar os dados para o servidor")
        if situacao.servidor_tem_dados:
            raise transferencia.DestinoComDados(
                "O servidor já tem dados. Os dados deste PC não foram enviados."
            )
        local = db.criar_engine(config.url_local())
        remoto = db.criar_engine(config.url_servidor(ligacao, senha))
        try:
            resultado = transferencia.copiar(local, remoto)
        except SQLAlchemyError as erro:
            raise ErroDeLigacao(explicar(erro)) from None
        finally:
            local.dispose()
            remoto.dispose()
    config.guardar_ligacao(ligacao, senha)
    return resultado
