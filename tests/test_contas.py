"""Contas de login: palavras-passe, autenticação, perfis e permissões nos ecrãs."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from PySide6.QtCore import Qt
from sqlalchemy import select

from lsc_presencas import contas, fecho, importacao, presencas
from lsc_presencas.demo import MES_DEMO, semear
from lsc_presencas.modelos import (
    PERFIL_ADMIN,
    PERFIL_UTILIZADOR,
    Auditoria,
    Cliente,
    Empresa,
    ParametrosEmpresa,
    Trabalhador,
    Utilizador,
)
from lsc_presencas.ui.app import JanelaPrincipal
from lsc_presencas.ui.ecra_contas import (
    DialogoConta,
    DialogoLogin,
    DialogoSenha,
    EcraContas,
)
from lsc_presencas.ui.ecra_fecho import EcraFecho
from lsc_presencas.ui.ecra_tabelas import EcraTabelas
from lsc_presencas.ui.ecra_trabalhadores import EcraTrabalhadores, FichaTrabalhador

ANO, MES = MES_DEMO
EDITAR = Qt.ItemDataRole.EditRole
SENHA = "segredo-123"


@pytest.fixture
def bd(fabrica):
    with fabrica(expire_on_commit=True) as sessao:
        semear(sessao)
        for p in sessao.scalars(select(ParametrosEmpresa)):
            p.subsidio_alimentacao_dia = Decimal("6")
            p.ajuda_custo_franca_dia = Decimal("50")
            p.prevencao_dia = Decimal("30")
            p.taxa_seguranca_social = Decimal("0.11")
        sessao.commit()
        yield sessao


@pytest.fixture
def admin(bd):
    return contas.criar(bd, "Pedro", "Pedro Teste", SENHA, PERFIL_ADMIN)


@pytest.fixture
def ana(bd, admin):
    return contas.criar(bd, "ana", "Ana Teste", SENHA)


# --- Palavras-passe ---------------------------------------------------------------------------


def test_a_palavra_passe_nao_fica_guardada_em_claro(bd, admin):
    assert SENHA not in admin.senha_hash and admin.senha_hash.startswith("scrypt$")
    assert contas.senha_confere(SENHA, admin.senha_hash)
    assert not contas.senha_confere("outra-coisa", admin.senha_hash)
    assert not contas.senha_confere(SENHA, "lixo")
    # O mesmo texto dá resumos diferentes (sal próprio de cada conta).
    assert contas.resumir_senha(SENHA) != contas.resumir_senha(SENHA)
    for registo in bd.scalars(select(Auditoria)):
        assert SENHA not in (registo.valor_novo or "") + (registo.valor_antigo or "")


def test_regras_ao_criar_contas(bd):
    with pytest.raises(contas.ErroDeConta, match="primeira conta"):
        contas.criar(bd, "ana", "Ana", SENHA, PERFIL_UTILIZADOR)
    with pytest.raises(contas.ErroDeConta, match="pelo menos 8"):
        contas.criar(bd, "pedro", "Pedro", "curta", PERFIL_ADMIN)
    contas.criar(bd, " Pedro ", "Pedro", SENHA, PERFIL_ADMIN)
    assert contas.procurar(bd, "PEDRO").nome_utilizador == "pedro"
    for nome, pessoa, motivo in (
        ("pedro", "Outro", "Já existe"),
        ("", "X", "obrigatório"),
        ("com espaco", "X", "espaços"),
        ("joao", " ", "nome da pessoa"),
    ):
        with pytest.raises(contas.ErroDeConta, match=motivo):
            contas.criar(bd, nome, pessoa, SENHA)
    assert bd.scalars(select(Auditoria).where(Auditoria.entidade == "conta")).one().acao == "criar"


def test_autenticar_e_bloqueio_por_tentativas(bd, admin):
    agora = datetime(2027, 1, 4, 9, 0)
    assert contas.autenticar(bd, "PEDRO", SENHA, agora).id == admin.id
    assert admin.ultimo_login == agora
    with pytest.raises(contas.ErroDeConta, match="incorretos"):
        contas.autenticar(bd, "ninguem", SENHA, agora)

    for _ in range(contas.MAX_TENTATIVAS):
        with pytest.raises(contas.ErroDeConta, match="incorretos"):
            contas.autenticar(bd, "pedro", "errada-123", agora)
    with pytest.raises(contas.ErroDeConta, match="bloqueada"):
        contas.autenticar(bd, "pedro", SENHA, agora)  # mesmo com a palavra-passe certa
    depois = agora + contas.BLOQUEIO + timedelta(seconds=1)
    assert contas.autenticar(bd, "pedro", SENHA, depois).id == admin.id
    assert admin.tentativas_falhadas == 0 and admin.bloqueado_ate is None


def test_conta_desativada_nao_entra(bd, admin, ana):
    contas.alterar(bd, ana, ativo=False)
    with pytest.raises(contas.ErroDeConta, match="incorretos"):
        contas.autenticar(bd, "ana", SENHA)


def test_tem_de_ficar_sempre_um_administrador_ativo(bd, admin, ana):
    for mudanca in ({"perfil": PERFIL_UTILIZADOR}, {"ativo": False}):
        with pytest.raises(contas.ErroDeConta, match="pelo menos um administrador"):
            contas.alterar(bd, admin, **mudanca)
    contas.alterar(bd, ana, perfil=PERFIL_ADMIN)
    contas.alterar(bd, admin, perfil=PERFIL_UTILIZADOR)  # agora já pode
    assert admin.perfil == PERFIL_UTILIZADOR


def test_permissoes_por_perfil(bd, admin, ana):
    empresa = bd.scalars(select(Empresa)).first()
    assert contas.e_admin()  # sem login não há restrições (testes, linha de comandos)

    contas.iniciar_sessao(ana)
    assert not contas.e_admin()
    assert presencas.utilizador_atual() == "ana"
    for operacao in (
        lambda: fecho.fechar(bd, empresa.id, ANO, MES, confirmado=True),
        lambda: fecho.reabrir(bd, empresa.id, ANO, MES, "motivo"),
        lambda: contas.criar(bd, "novo", "Novo", SENHA),
        lambda: contas.alterar(bd, ana, perfil=PERFIL_ADMIN),
        lambda: contas.definir_senha(bd, admin, "outra-senha-1"),
        lambda: importacao.gravar(bd, None, [], {}),
    ):
        with pytest.raises(contas.SemPermissao):
            operacao()
    contas.definir_senha(bd, ana, "nova-senha-1")  # a própria pode
    assert contas.autenticar(bd, "ana", "nova-senha-1")

    # O utilizador marca presenças, e a auditoria fica com o nome da conta.
    codigo = presencas.codigos_ativos(bd)["FE"]
    t = bd.scalars(select(Trabalhador).where(Trabalhador.ativo)).first()
    presencas.aplicar_alteracoes(
        bd, [presencas.Alteracao(t.id, date(ANO, MES, 14), (codigo, Decimal(0)))]
    )
    registo = bd.scalars(select(Auditoria).where(Auditoria.entidade == "marcacao")).one()
    assert registo.utilizador == "ana"

    contas.iniciar_sessao(admin)
    assert fecho.fechar(bd, empresa.id, ANO, MES, confirmado=True).fechado_por == "pedro"


def test_recuperacao_repoe_a_palavra_passe_sem_login(bd, admin):
    contas.terminar_sessao()
    admin.bloqueado_ate = datetime.now() + timedelta(minutes=5)
    bd.commit()
    contas.definir_senha(bd, admin, "recuperada-1", recuperacao=True)
    assert contas.autenticar(bd, "pedro", "recuperada-1")
    registo = bd.scalars(select(Auditoria).where(Auditoria.motivo.is_not(None))).one()
    assert "Recuperação" in registo.motivo


# --- Ecrãs ------------------------------------------------------------------------------------


def test_dialogo_da_primeira_conta_e_login(app, bd):
    primeira = DialogoConta(bd, primeira=True)
    assert not primeira.caixa_perfil.isEnabled()
    primeira.campo_utilizador.setText("pedro")
    primeira.campo_nome.setText("Pedro Teste")
    primeira.campo_senha.setText(SENHA)
    primeira.campo_repetir.setText("diferente-1")
    assert not primeira.confirmar() and "não são iguais" in primeira.erro.text()
    primeira.campo_repetir.setText(SENHA)
    assert primeira.confirmar() and primeira.conta.perfil == PERFIL_ADMIN

    login = DialogoLogin(bd)
    login.campo_utilizador.setText("pedro")
    login.campo_senha.setText("errada-123")
    assert not login.confirmar() and "incorretos" in login.erro.text()
    assert login.campo_senha.text() == ""  # a palavra-passe não fica no campo
    login.campo_senha.setText(SENHA)
    assert login.confirmar() and login.conta.nome_utilizador == "pedro"


def test_ecra_de_contas(app, bd, admin, ana):
    contas.iniciar_sessao(admin)
    ecra = EcraContas(bd)
    assert ecra.tabela.rowCount() == 2
    assert not ecra.mudar_perfil() and "Selecione" in ecra.mensagem.text()

    ecra.selecionar("ana")
    assert ecra.mudar_perfil() and ana.perfil == PERFIL_ADMIN
    assert ecra.alternar_ativa() and not ana.ativo
    ecra.selecionar("pedro")
    assert not ecra.alternar_ativa()  # era o único administrador ativo
    assert "pelo menos um administrador" in ecra.mensagem.text()

    dialogo = DialogoSenha(bd, ana)
    dialogo.campo_senha.setText("reposta-123")
    dialogo.campo_repetir.setText("reposta-123")
    assert dialogo.confirmar()
    assert contas.senha_confere("reposta-123", ana.senha_hash)


def test_utilizador_ve_mas_nao_altera_tabelas_fichas_nem_fecho(app, bd, admin, ana):
    contas.iniciar_sessao(ana)
    empresa = bd.scalars(select(Empresa)).first()

    tabelas = EcraTabelas(bd)
    tabelas.recarregar()
    vista = tabelas.vistas["Clientes"]
    erros = []
    vista.modelo.erro.connect(erros.append)
    assert not vista.botao_novo.isEnabled() and not vista.botao_apagar.isEnabled()
    assert not vista.modelo.setData(vista.modelo.index(0, 0), "mudado", EDITAR)
    assert "permissão" in erros[-1]
    assert not vista.modelo.apagar(0)
    assert "mudado" not in bd.scalars(select(Cliente.codigo)).all()

    trabalhadores = EcraTrabalhadores(bd)
    trabalhadores.recarregar()
    assert not trabalhadores.vista.botao_novo.isEnabled()
    t = bd.scalars(select(Trabalhador).where(Trabalhador.ativo)).first()
    nome = t.nome
    ficha = FichaTrabalhador(bd, t)
    assert not ficha.botao_guardar.isEnabled() and not ficha.salarios.botao_novo.isEnabled()
    ficha.dados.campos["nome"].setText("Outro Nome")
    assert not ficha.guardar()
    bd.refresh(t)
    assert t.nome == nome

    ecra_fecho = EcraFecho(bd)
    ecra_fecho.escolher(empresa.id, ANO, MES)
    assert not ecra_fecho.botao_fechar.isEnabled()
    assert "administrador" in ecra_fecho.botao_fechar.toolTip()
    assert not ecra_fecho.fechar() and "administrador" in ecra_fecho.mensagem.text()
    assert ecra_fecho.exportar()  # exportar (provisório) pode

    # O administrador volta a poder alterar, nos mesmos ecrãs.
    contas.iniciar_sessao(admin)
    tabelas.recarregar()
    assert vista.botao_novo.isEnabled()
    assert vista.modelo.setData(vista.modelo.index(0, 0), "mudado", EDITAR)


def test_janela_esconde_os_ecras_de_administrador(app, fabrica):
    with fabrica() as sessao:
        semear(sessao)
        admin = contas.criar(sessao, "pedro", "Pedro Teste", SENHA, PERFIL_ADMIN)
        ana = contas.criar(sessao, "ana", "Ana Teste", SENHA)
        sessao.commit()

    contas.iniciar_sessao(ana)
    janela = JanelaPrincipal(fabrica)
    nomes = set(janela.ecras)
    assert {"Presenças", "Lançamentos", "Fecho do mês", "Relatórios"} <= nomes
    assert not {"Contas", "Auditoria", "Base de dados"} & nomes
    assert "Ana Teste" in janela.rotulo_sessao.text()
    assert "Utilizador" in janela.rotulo_sessao.text()
    janela.terminar_sessao()
    assert janela.terminou_sessao

    contas.iniciar_sessao(admin)
    janela = JanelaPrincipal(fabrica)
    assert {"Contas", "Auditoria", "Base de dados"} <= set(janela.ecras)
    janela.close()


def test_as_contas_ficam_na_tabela_utilizador(bd, admin, ana):
    assert [c.nome_utilizador for c in contas.listar(bd)] == ["ana", "pedro"]
    assert bd.scalars(select(Utilizador.perfil).order_by(Utilizador.id)).all() == [
        PERFIL_ADMIN,
        PERFIL_UTILIZADOR,
    ]
