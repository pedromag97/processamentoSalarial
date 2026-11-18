"""Contas de login: palavras-passe, autenticação, perfis e a sessão em curso.

Sem interface. A palavra-passe nunca é guardada nem registada: guarda-se só o resumo (scrypt,
com sal próprio de cada conta).

Dois perfis:
- administrador: faz tudo;
- utilizador: marca presenças, faz lançamentos, vê e exporta; não altera fichas, salários,
  tabelas nem parâmetros, não fecha nem reabre meses, não importa e não gere contas.

Quando ninguém fez login (testes, linha de comandos), não há restrições: quem chama é
tratado como administrador e a auditoria usa o utilizador do Windows.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import auditoria
from .modelos import PERFIL_ADMIN, PERFIL_UTILIZADOR, Utilizador

PERFIS = {PERFIL_ADMIN: "Administrador", PERFIL_UTILIZADOR: "Utilizador"}
TAMANHO_MINIMO = 8
MAX_TENTATIVAS = 5
BLOQUEIO = timedelta(minutes=5)

_N, _R, _P = 2**14, 8, 1


class ErroDeConta(ValueError):
    """Pedido inválido sobre uma conta (mensagem para mostrar ao utilizador)."""


class SemPermissao(PermissionError):
    """A conta em sessão não tem permissão para a operação."""


# --- Palavras-passe ---------------------------------------------------------------------------


def resumir_senha(senha: str) -> str:
    sal = secrets.token_bytes(16)
    resumo = hashlib.scrypt(senha.encode("utf-8"), salt=sal, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${sal.hex()}${resumo.hex()}"


def senha_confere(senha: str, guardado: str) -> bool:
    try:
        metodo, n, r, p, sal, resumo = guardado.split("$")
        if metodo != "scrypt":
            return False
        calculado = hashlib.scrypt(
            senha.encode("utf-8"),
            salt=bytes.fromhex(sal),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(resumo) // 2,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calculado.hex(), resumo)


def validar_senha(senha: str) -> None:
    if len(senha or "") < TAMANHO_MINIMO:
        raise ErroDeConta(f"A palavra-passe tem de ter pelo menos {TAMANHO_MINIMO} caracteres.")


def normalizar(nome_utilizador: str) -> str:
    return (nome_utilizador or "").strip().casefold()


# --- Sessão em curso --------------------------------------------------------------------------


@dataclass(frozen=True)
class Sessao:
    id: int
    nome_utilizador: str
    nome: str
    perfil: str


_atual: Sessao | None = None


def atual() -> Sessao | None:
    return _atual


def iniciar_sessao(utilizador: Utilizador) -> Sessao:
    global _atual
    _atual = Sessao(utilizador.id, utilizador.nome_utilizador, utilizador.nome, utilizador.perfil)
    return _atual


def terminar_sessao() -> None:
    global _atual
    _atual = None


def e_admin() -> bool:
    """True para o administrador e também quando não há login (testes, linha de comandos)."""
    return _atual is None or _atual.perfil == PERFIL_ADMIN


def exigir_admin(operacao: str) -> None:
    if not e_admin():
        raise SemPermissao(f"Só um administrador pode {operacao}.")


# --- Consultar e autenticar -------------------------------------------------------------------


def ha_contas(sessao: Session) -> bool:
    return bool(sessao.scalar(select(func.count()).select_from(Utilizador)))


def procurar(sessao: Session, nome_utilizador: str) -> Utilizador | None:
    return sessao.scalars(
        select(Utilizador).where(Utilizador.nome_utilizador == normalizar(nome_utilizador))
    ).first()


def autenticar(
    sessao: Session, nome_utilizador: str, senha: str, agora: datetime | None = None
) -> Utilizador:
    """Devolve a conta se o nome e a palavra-passe estiverem certos; senão levanta ErroDeConta.

    Ao fim de 5 tentativas falhadas seguidas, a conta fica bloqueada durante 5 minutos.
    A mensagem de erro é a mesma para conta inexistente e palavra-passe errada.
    """
    agora = agora or datetime.now()
    falhou = ErroDeConta("Nome de utilizador ou palavra-passe incorretos.")
    conta = procurar(sessao, nome_utilizador)
    if conta is None:
        resumir_senha(senha or "")  # demora o mesmo que uma verificação verdadeira
        raise falhou
    if conta.bloqueado_ate and conta.bloqueado_ate > agora:
        minutos = int((conta.bloqueado_ate - agora).total_seconds() // 60) + 1
        raise ErroDeConta(
            f"Conta bloqueada por tentativas falhadas. Tente daqui a {minutos} minuto(s)."
        )
    if not conta.ativo or not senha_confere(senha or "", conta.senha_hash):
        conta.tentativas_falhadas = (conta.tentativas_falhadas or 0) + 1
        if conta.tentativas_falhadas >= MAX_TENTATIVAS:
            conta.bloqueado_ate = agora + BLOQUEIO
            conta.tentativas_falhadas = 0
        sessao.commit()
        raise falhou
    conta.tentativas_falhadas = 0
    conta.bloqueado_ate = None
    conta.ultimo_login = agora
    sessao.commit()
    return conta


# --- Gerir contas -----------------------------------------------------------------------------


def _admins_ativos(sessao: Session, exceto_id: int | None = None) -> int:
    consulta = (
        select(func.count())
        .select_from(Utilizador)
        .where(Utilizador.perfil == PERFIL_ADMIN, Utilizador.ativo)
    )
    if exceto_id is not None:
        consulta = consulta.where(Utilizador.id != exceto_id)
    return sessao.scalar(consulta) or 0


def _descrever(conta: Utilizador) -> dict:
    return {
        "conta": conta.nome_utilizador,
        "nome": conta.nome,
        "perfil": PERFIS.get(conta.perfil, conta.perfil),
        "ativa": bool(conta.ativo),
    }


def criar(
    sessao: Session, nome_utilizador: str, nome: str, senha: str, perfil: str = PERFIL_UTILIZADOR
) -> Utilizador:
    """Cria uma conta. A primeira conta de todas tem de ser de administrador."""
    primeira = not ha_contas(sessao)
    if not primeira:
        exigir_admin("criar contas")
    login = normalizar(nome_utilizador)
    if not login or " " in login:
        raise ErroDeConta("O nome de utilizador é obrigatório e não pode ter espaços.")
    if not (nome or "").strip():
        raise ErroDeConta("O nome da pessoa é obrigatório.")
    if perfil not in PERFIS:
        raise ErroDeConta("Perfil desconhecido.")
    if primeira and perfil != PERFIL_ADMIN:
        raise ErroDeConta("A primeira conta tem de ser de administrador.")
    validar_senha(senha)
    if procurar(sessao, login) is not None:
        raise ErroDeConta(f"Já existe uma conta «{login}».")
    try:
        conta = Utilizador(
            nome_utilizador=login,
            nome=nome.strip(),
            perfil=perfil,
            ativo=True,
            senha_hash=resumir_senha(senha),
        )
        sessao.add(conta)
        sessao.flush()
        auditoria.registar(sessao, "conta", conta.id, "criar", None, _descrever(conta))
        sessao.commit()
    except Exception:
        sessao.rollback()
        raise
    return conta


def alterar(
    sessao: Session,
    conta: Utilizador,
    *,
    nome: str | None = None,
    perfil: str | None = None,
    ativo: bool | None = None,
) -> None:
    """Muda o nome, o perfil ou o estado. Tem de ficar sempre um administrador ativo."""
    exigir_admin("alterar contas")
    novo_perfil = conta.perfil if perfil is None else perfil
    novo_ativo = conta.ativo if ativo is None else ativo
    if novo_perfil not in PERFIS:
        raise ErroDeConta("Perfil desconhecido.")
    if nome is not None and not nome.strip():
        raise ErroDeConta("O nome da pessoa é obrigatório.")
    deixa_de_ser_admin = (
        conta.perfil == PERFIL_ADMIN
        and conta.ativo
        and (novo_perfil != PERFIL_ADMIN or not novo_ativo)
    )
    if deixa_de_ser_admin and _admins_ativos(sessao, exceto_id=conta.id) == 0:
        raise ErroDeConta("Tem de ficar pelo menos um administrador ativo.")
    try:
        antes = _descrever(conta)
        if nome is not None:
            conta.nome = nome.strip()
        conta.perfil = novo_perfil
        conta.ativo = novo_ativo
        depois = _descrever(conta)
        if depois != antes:
            auditoria.registar(sessao, "conta", conta.id, "alterar", antes, depois)
        sessao.commit()
    except Exception:
        sessao.rollback()
        raise


def definir_senha(sessao: Session, conta: Utilizador, senha: str, *, recuperacao=False) -> None:
    """Define uma palavra-passe nova e desbloqueia a conta.

    Um administrador pode repor a de qualquer conta; cada pessoa pode mudar a sua.
    `recuperacao=True` é o comando de recuperação corrido no PC (sem login).
    """
    sessao_atual = atual()
    propria = sessao_atual is not None and sessao_atual.id == conta.id
    if not recuperacao and not propria:
        exigir_admin("repor a palavra-passe de outra conta")
    validar_senha(senha)
    try:
        conta.senha_hash = resumir_senha(senha)
        conta.tentativas_falhadas = 0
        conta.bloqueado_ate = None
        auditoria.registar(
            sessao,
            "conta",
            conta.id,
            "alterar",
            None,
            {"conta": conta.nome_utilizador, "palavra-passe": "alterada"},
            motivo="Recuperação no PC (sem login)" if recuperacao else None,
        )
        sessao.commit()
    except Exception:
        sessao.rollback()
        raise


def listar(sessao: Session) -> list[Utilizador]:
    return list(sessao.scalars(select(Utilizador).order_by(Utilizador.nome_utilizador)))
