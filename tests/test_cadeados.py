"""Cadeados: um funcionário em que alguém está a mexer fica bloqueado para os outros."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt
from sqlalchemy import func, select, update

from lsc_presencas import bloqueios, contas, lancamentos, presencas, transferencia
from lsc_presencas.demo import MES_DEMO, semear
from lsc_presencas.modelos import (
    PERFIL_ADMIN,
    BloqueioTrabalhador,
    LancamentoManual,
    Trabalhador,
)
from lsc_presencas.presencas import Alteracao
from lsc_presencas.ui.app import JanelaPrincipal
from lsc_presencas.ui.ecra_presencas import EcraPresencas
from lsc_presencas.ui.ecra_trabalhadores import EcraTrabalhadores, FichaTrabalhador
from lsc_presencas.ui.grelha import CADEADO, TRABALHADOR

ANO, MES = MES_DEMO
DIA = date(ANO, MES, 14)
ZERO = Decimal(0)
OUTRO = "programa-de-outra-pessoa"  # outro programa aberto (outro PC)
EDITAVEL = Qt.ItemFlag.ItemIsEditable
MOSTRAR = Qt.ItemDataRole.DisplayRole
DICA = Qt.ItemDataRole.ToolTipRole


@pytest.fixture(params=["sqlite", "postgresql"])
def bd(request):
    """Os mesmos testes no ficheiro local e num servidor PostgreSQL."""
    fabrica = request.getfixturevalue("fabrica" if request.param == "sqlite" else "fabrica_pg")
    with fabrica(expire_on_commit=True) as sessao:
        semear(sessao)
        sessao.commit()
        yield sessao


def dois_trabalhadores(sessao):
    return sessao.scalars(
        select(Trabalhador).where(Trabalhador.ativo).order_by(Trabalhador.numero).limit(2)
    ).all()


def contar(sessao) -> int:
    return sessao.scalar(select(func.count()).select_from(BloqueioTrabalhador))


def por_a_ana_a_mexer(sessao, trabalhador_id) -> None:
    """Outra pessoa (a Ana, noutro PC) fica com o cadeado do funcionário."""
    em_sessao = contas.atual()
    contas.iniciar_sessao(contas.procurar(sessao, "ana") or _criar_ana(sessao))
    assert bloqueios.definir(sessao, [trabalhador_id], programa=OUTRO) == {}
    contas.terminar_sessao()
    if em_sessao is not None:
        contas.iniciar_sessao(sessao.get(type(contas.procurar(sessao, "ana")), em_sessao.id))


def _criar_ana(sessao):
    contas.criar(sessao, "chefe", "Chefe Teste", "segredo-123", PERFIL_ADMIN)
    return contas.criar(sessao, "ana", "Ana Teste", "segredo-123")


def indice(modelo, trabalhador_id, dia):
    linha = next(
        n
        for n, x in enumerate(modelo.linhas)
        if x.tipo == TRABALHADOR and x.trab.id == trabalhador_id
    )
    return modelo.index(linha, modelo.coluna_do_dia(dia))


# --- Núcleo -----------------------------------------------------------------------------------


def test_pedir_largar_e_ver_os_cadeados_dos_outros(bd):
    um, dois = dois_trabalhadores(bd)
    assert bloqueios.definir(bd, [um.id]) == {}
    assert bloqueios.de_outros(bd) == {}  # os meus não me bloqueiam
    visto_de_fora = bloqueios.de_outros(bd, programa=OUTRO)
    assert list(visto_de_fora) == [um.id]
    assert "Em uso por" in visto_de_fora[um.id].descricao

    # Outra pessoa não consegue o mesmo funcionário, mas consegue outro.
    recusados = bloqueios.definir(bd, [um.id, dois.id], programa=OUTRO)
    assert list(recusados) == [um.id]
    assert list(bloqueios.de_outros(bd)) == [dois.id]

    # Mudar a seleção larga os que já não interessam: eu largo o primeiro, a outra pessoa
    # passa a ter só esse (e larga o segundo).
    assert bloqueios.definir(bd, []) == {}
    assert bloqueios.definir(bd, [um.id], programa=OUTRO) == {}
    assert list(bloqueios.de_outros(bd)) == [um.id]
    bloqueios.largar(bd, programa=OUTRO)
    assert contar(bd) == 0


def test_pedir_mantem_os_que_ja_tinha(bd):
    um, dois = dois_trabalhadores(bd)
    assert bloqueios.pedir(bd, um.id) is None
    assert bloqueios.pedir(bd, dois.id) is None
    assert contar(bd) == 2
    tomado = bloqueios.pedir(bd, um.id, programa=OUTRO)
    assert tomado is not None and tomado.trabalhador_id == um.id
    bloqueios.largar(bd, [um.id])
    assert bloqueios.pedir(bd, um.id, programa=OUTRO) is None


def test_cadeado_abandonado_deixa_de_contar(bd):
    um, _ = dois_trabalhadores(bd)
    bloqueios.definir(bd, [um.id], programa=OUTRO)
    assert um.id in bloqueios.de_outros(bd)
    bloqueios.renovar(bd, programa=OUTRO)  # o outro programa continua aberto
    assert um.id in bloqueios.de_outros(bd)

    # O outro programa fechou mal: há mais de 90 segundos que não renova.
    bd.execute(
        update(BloqueioTrabalhador).values(
            renovado_em=bloqueios.agora(bd) - bloqueios.VALIDADE - timedelta(seconds=5)
        )
    )
    bd.commit()
    assert bloqueios.de_outros(bd) == {}
    assert bloqueios.definir(bd, [um.id]) == {}  # e outra pessoa pode ficar com ele
    assert contar(bd) == 1


def test_funcionario_com_cadeado_nao_e_alterado_por_outros(bd):
    um, dois = dois_trabalhadores(bd)
    codigo = presencas.codigos_ativos(bd)["FE"]
    bloqueios.definir(bd, [um.id], programa=OUTRO)

    antes = bd.scalar(select(func.count()).select_from(presencas.Marcacao))
    with pytest.raises(bloqueios.Bloqueado, match=um.nome):
        presencas.aplicar_alteracoes(bd, [Alteracao(t.id, DIA, (codigo, ZERO)) for t in (um, dois)])
    bd.expire_all()  # tudo ou nada: nem o funcionário livre foi alterado
    assert bd.scalar(select(func.count()).select_from(presencas.Marcacao)) == antes
    presencas.aplicar_alteracoes(bd, [Alteracao(dois.id, DIA, (codigo, ZERO))])

    lanc = LancamentoManual(
        trabalhador_id=um.id, ano=ANO, mes=MES, tipo="premio", descricao="x", valor=Decimal(10)
    )
    bd.add(lanc)
    bd.flush()
    with pytest.raises(bloqueios.Bloqueado):
        lancamentos.registar(bd, lanc, "criar")
    bd.rollback()

    # Quem tem o cadeado altera à vontade; depois de o largar, os outros também.
    bloqueios.largar(bd, programa=OUTRO)
    bloqueios.definir(bd, [um.id])
    presencas.aplicar_alteracoes(bd, [Alteracao(um.id, DIA, (codigo, ZERO))])


def test_os_cadeados_nao_vao_nas_copias(bd, tmp_path):
    um, _ = dois_trabalhadores(bd)
    bloqueios.definir(bd, [um.id])
    assert "bloqueio_trabalhador" not in transferencia.contar(bd.get_bind())


# --- Grelha -----------------------------------------------------------------------------------


def test_a_selecao_na_grelha_poe_o_cadeado(app, bd):
    um, dois = dois_trabalhadores(bd)
    ecra = EcraPresencas(bd)
    ecra.ir_para(DIA)
    modelo = ecra.modelo
    assert ecra.pedir_cadeados() == {} and contar(bd) == 0  # nada selecionado

    selecao = ecra.dias.selectionModel()
    selecao.select(indice(modelo, um.id, DIA), QItemSelectionModel.SelectionFlag.Select)
    assert ecra.temporizador_cadeados.isActive()  # pede-os daí a um instante
    assert ecra.pedir_cadeados() == {}
    assert list(bloqueios.de_outros(bd, programa=OUTRO)) == [um.id]

    # Mudar a seleção para outro funcionário muda o cadeado.
    selecao.select(indice(modelo, dois.id, DIA), QItemSelectionModel.SelectionFlag.ClearAndSelect)
    ecra.pedir_cadeados()
    assert list(bloqueios.de_outros(bd, programa=OUTRO)) == [dois.id]
    selecao.clearSelection()
    ecra.pedir_cadeados()
    assert contar(bd) == 0


def test_a_grelha_mostra_o_cadeado_e_fica_so_de_leitura(app, bd):
    um, dois = dois_trabalhadores(bd)
    ecra = EcraPresencas(bd)
    ecra.ir_para(DIA)
    modelo = ecra.modelo
    celula, livre = indice(modelo, um.id, DIA), indice(modelo, dois.id, DIA)
    nome = modelo.index(celula.row(), 1)
    assert modelo.flags(celula) & EDITAVEL and CADEADO not in modelo.data(nome, MOSTRAR)

    por_a_ana_a_mexer(bd, um.id)
    assert ecra.atualizar(manual=True)  # o que o temporizador faz de 15 em 15 segundos
    assert modelo.data(nome, MOSTRAR) == f"{CADEADO} {um.nome}"
    assert "Em uso por Ana Teste" in modelo.data(nome, DICA)
    assert "Em uso por Ana Teste" in modelo.data(celula, DICA)
    assert not (modelo.flags(celula) & EDITAVEL)
    assert modelo.flags(livre) & EDITAVEL

    # Mesmo que a grelha ainda não soubesse do cadeado, o núcleo recusa a gravação.
    erros = []
    modelo.erro.connect(erros.append)
    assert not modelo.aplicar_texto([celula, livre], "FE")
    assert "outra pessoa" in erros[-1] and um.nome in erros[-1]

    # Selecionar um funcionário em uso avisa e não lhe tira o cadeado.
    ecra.dias.selectionModel().select(celula, QItemSelectionModel.SelectionFlag.Select)
    recusados = ecra.pedir_cadeados()
    assert list(recusados) == [um.id]
    assert "Ana Teste" in ecra.estado.text()

    bloqueios.largar(bd, programa=OUTRO)
    assert ecra.atualizar(manual=True)
    assert modelo.data(nome, MOSTRAR) == um.nome and modelo.flags(celula) & EDITAVEL
    assert modelo.aplicar_texto([celula], "FE")


# --- Ficha e lista de trabalhadores -----------------------------------------------------------


def test_abrir_a_ficha_poe_o_cadeado_e_fechar_larga_o(app, bd):
    um, _ = dois_trabalhadores(bd)
    ficha = FichaTrabalhador(bd, um)
    assert ficha.tem_cadeado and ficha.botao_guardar.isEnabled()
    assert list(bloqueios.de_outros(bd, programa=OUTRO)) == [um.id]
    ficha.dados.campos["nome"].setText("Nome Novo")
    assert ficha.guardar()  # guardar fecha a ficha
    assert contar(bd) == 0 and um.nome == "Nome Novo"

    cancelada = FichaTrabalhador(bd, um)
    assert contar(bd) == 1
    cancelada.reject()
    assert contar(bd) == 0


def test_ficha_em_uso_por_outra_pessoa_abre_so_para_consulta(app, bd):
    um, _ = dois_trabalhadores(bd)
    nome = um.nome
    por_a_ana_a_mexer(bd, um.id)

    ficha = FichaTrabalhador(bd, um)
    assert not ficha.tem_cadeado and not ficha.botao_guardar.isEnabled()
    assert "Em uso por Ana Teste" in ficha.erro.text()
    assert not ficha.salarios.botao_novo.isEnabled()
    ficha.dados.campos["nome"].setText("Não Devia Gravar")
    assert not ficha.guardar()
    ficha.reject()
    bd.refresh(um)
    assert um.nome == nome
    assert list(bloqueios.de_outros(bd)) == [um.id]  # fechar a consulta não tira o da Ana

    lista = EcraTrabalhadores(bd)
    lista.recarregar()
    modelo = lista.modelo
    coluna = next(n for n, c in enumerate(modelo.colunas) if c.campo == "cadeado")
    linha = modelo.linhas.index(um)
    assert modelo.data(modelo.index(linha, coluna), MOSTRAR) == CADEADO
    assert modelo.data(modelo.index(linha + 1, coluna), MOSTRAR) == ""


def test_utilizador_sem_permissao_consulta_a_ficha_sem_bloquear_ninguem(app, bd):
    um, _ = dois_trabalhadores(bd)
    contas.iniciar_sessao(_criar_ana(bd))
    ficha = FichaTrabalhador(bd, um)
    assert not ficha.tem_cadeado and contar(bd) == 0
    ficha.reject()


# --- Janela -----------------------------------------------------------------------------------


def test_sair_do_ecra_de_presencas_ou_fechar_o_programa_larga_os_cadeados(app, fabrica):
    with fabrica() as sessao:
        semear(sessao)
        sessao.commit()
    janela = JanelaPrincipal(fabrica)
    assert janela.temporizador_cadeados.isActive()
    ecra = janela.mostrar("Presenças")
    ecra.ir_para(DIA)
    um, _ = dois_trabalhadores(janela.sessao)
    celula = indice(ecra.modelo, um.id, DIA)
    ecra.dias.selectionModel().select(celula, QItemSelectionModel.SelectionFlag.Select)
    ecra.pedir_cadeados()
    assert contar(janela.sessao) == 1
    janela._renovar_cadeados()  # o que o temporizador faz de 30 em 30 segundos
    assert contar(janela.sessao) == 1

    janela.mostrar("Relatórios")
    assert contar(janela.sessao) == 0
    janela.mostrar("Presenças")  # ao voltar, a grelha é recarregada e não há seleção
    assert contar(janela.sessao) == 0
    celula = indice(ecra.modelo, um.id, DIA)
    ecra.dias.selectionModel().select(celula, QItemSelectionModel.SelectionFlag.Select)
    ecra.pedir_cadeados()
    assert contar(janela.sessao) == 1

    janela.close()
    with fabrica() as sessao:
        assert contar(sessao) == 0
