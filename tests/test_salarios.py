"""Folha de salário a partir da base de dados, e os valores escritos à mão em cada mês."""

from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select

from lsc_presencas import bloqueios, salarios
from lsc_presencas import folha_salario as fs
from lsc_presencas.modelos import (
    FECHO_FECHADO,
    GER_MENSAL,
    GER_QUANTIDADE_PREVENCAO,
    GER_SEMANAL,
    Auditoria,
    CodigoPresenca,
    Empresa,
    FechoMes,
    LancamentoManual,
    LinhaGer,
    Marcacao,
    ParametrosEmpresa,
    SalarioBase,
    Trabalhador,
)

ANO, MES = 2026, 11  # 21 dias de trabalho


@pytest.fixture
def bd(fabrica):
    with fabrica(expire_on_commit=True) as sessao:
        empresa = Empresa(nome="Empresa de Teste, Lda")
        sessao.add(empresa)
        sessao.flush()
        sessao.add(
            ParametrosEmpresa(
                empresa_id=empresa.id,
                inicio_vigencia=date(2026, 1, 1),
                subsidio_alimentacao_dia=D("8.50"),
                taxa_seguranca_social=D("0.11"),
            )
        )
        t = Trabalhador(numero=1, nome="Ana Exemplo", empresa_id=empresa.id)
        sessao.add(t)
        sessao.flush()
        sessao.add(
            SalarioBase(
                trabalhador_id=t.id,
                inicio_vigencia=date(2026, 1, 1),
                valor=D("920"),
                duodecimo_ferias=D("76.67"),
                duodecimo_natal=D("76.67"),
            )
        )
        sessao.commit()
        yield sessao


@pytest.fixture
def ana(bd):
    return bd.scalars(select(Trabalhador)).one()


def marcar(sessao, trabalhador, dias: dict[int, str]) -> None:
    codigos = {c.codigo: c.id for c in sessao.scalars(select(CodigoPresenca))}
    for dia, codigo in dias.items():
        sessao.add(
            Marcacao(
                trabalhador_id=trabalhador.id, data=date(ANO, MES, dia), codigo_id=codigos[codigo]
            )
        )
    sessao.commit()


def linha_ger(sessao, trabalhador, nome, unidade, valor, **campos) -> LinhaGer:
    linha = LinhaGer(
        trabalhador_id=trabalhador.id, nome=nome, unidade=unidade, valor=valor, **campos
    )
    sessao.add(linha)
    sessao.commit()
    return linha


EXEMPLO = {2: "P", 3: "P", 4: "FI", 5: "FI", 6: "P", 9: "P", 10: "FI", 11: "P", 12: "P", 13: "P"}


def test_os_codigos_base_sabem_como_contam_na_folha(bd):
    conta = dict(bd.execute(select(CodigoPresenca.codigo, CodigoPresenca.conta_folha)).all())
    assert conta["P"] == conta["PF"] == conta["PR"] == "trabalho"
    assert conta["FE"] == "ferias"
    assert conta["FI"] == "falta"
    assert conta["B"] == conta["AT"] == "baixa"
    assert conta["FER"] == conta["FJ"] == conta["DF"] == ""


def test_folha_conta_os_dias_da_grelha(bd, ana):
    marcar(bd, ana, EXEMPLO)
    f = salarios.folha_do_trabalhador(bd, ana, ANO, MES)
    assert f.folha.dias_trabalho_mes == 21
    assert f.folha.linha(fs.PRESENCAS).quantidade == 7
    assert f.folha.linha(fs.FALTAS).quantidade == 3
    assert f.folha.linha(fs.PRESENCAS).total == D("306.67")
    assert f.folha.linha(fs.SUBSIDIO_ALIMENTACAO).total == D("59.50")
    assert f.folha.linha(fs.SUBSIDIO_FERIAS).total == D("25.56")
    assert f.folha.linha(fs.SEGURANCA_SOCIAL).total == D("-24.90")
    assert f.folha.vencimento_rc == D("260.96")
    assert f.contagens == {"P": 7, "FI": 3}


def test_ferias_e_baixa_vem_dos_codigos(bd, ana):
    marcar(bd, ana, {2: "FE", 3: "FE", 4: "B", 5: "AT", 6: "FJ", 9: "FER"})
    folha = salarios.folha_do_trabalhador(bd, ana, ANO, MES).folha
    assert folha.linha(fs.FERIAS).quantidade == 2
    assert folha.linha(fs.BAIXA).quantidade == 2
    assert folha.linha(fs.FALTAS).quantidade == 0
    assert folha.linha(fs.PRESENCAS).quantidade == 0


def test_sem_salario_nem_parametros_a_folha_fica_incompleta(bd):
    outra = Empresa(nome="Outra, Lda")
    bd.add(outra)
    bd.flush()
    t = Trabalhador(numero=2, nome="Rui Exemplo", empresa_id=outra.id)
    bd.add(t)
    bd.commit()
    folha = salarios.folha_do_trabalhador(bd, t, ANO, MES).folha
    assert folha.incompleta
    assert {"sem_salario_base", "sem_taxa_seguranca_social"} <= folha.chaves_de_alerta()


def test_subsidio_de_alimentacao_de_excecao_do_trabalhador(bd, ana):
    ana.exc_subsidio_alimentacao = D("10")
    marcar(bd, ana, {2: "P", 3: "P"})
    folha = salarios.folha_do_trabalhador(bd, ana, ANO, MES).folha
    assert folha.linha(fs.SUBSIDIO_ALIMENTACAO).total == D("20.00")


def test_linhas_ger_com_quantidade_escrita_e_contada(bd, ana):
    marcar(bd, ana, {9: "PR", 10: "PR", 11: "PR", 12: "P"})
    ajuda = linha_ger(bd, ana, "Ajuda", "dia", D("200"), base=GER_MENSAL, ordem=1)
    horas = linha_ger(bd, ana, "Banco de horas", "hora", D("8.125"), ordem=2)
    linha_ger(
        bd,
        ana,
        "Dias de prevenção",
        "dia",
        D("100"),
        base=GER_SEMANAL,
        quantidade_de=GER_QUANTIDADE_PREVENCAO,
        ordem=3,
    )
    linha_ger(bd, ana, "Antiga", "dia", D("1"), ativo=False, ordem=4)

    salarios.gravar_quantidade(bd, ajuda.id, ANO, MES, D("10"))
    salarios.gravar_quantidade(bd, horas.id, ANO, MES, D("8"))
    f = salarios.folha_do_trabalhador(bd, ana, ANO, MES)

    assert [(x.descricao, x.total) for x in f.folha.linhas_ger] == [
        ("Ajuda", D("95.24")),
        ("Banco de horas", D("65.00")),
        ("Dias de prevenção", D("42.86")),  # 3 dias PR × 100 / 7
    ]
    assert [manual for _id, manual in f.linhas_ger] == [True, True, False]
    assert f.folha.linha(fs.PRESENCAS).quantidade == 4  # PR também conta como trabalhado


def test_quantidade_de_outro_mes_nao_conta(bd, ana):
    horas = linha_ger(bd, ana, "Banco de horas", "hora", D("8.125"))
    salarios.gravar_quantidade(bd, horas.id, ANO, 10, D("5"))
    folha = salarios.folha_do_trabalhador(bd, ana, ANO, MES).folha
    assert folha.linhas_ger[0].quantidade == 0


def test_quantidade_contada_da_grelha_nao_se_escreve(bd, ana):
    prev = linha_ger(bd, ana, "Prevenção", "dia", D("100"), quantidade_de=GER_QUANTIDADE_PREVENCAO)
    with pytest.raises(ValueError, match="grelha"):
        salarios.gravar_quantidade(bd, prev.id, ANO, MES, D("3"))
    with pytest.raises(ValueError, match="negativa"):
        salarios.gravar_quantidade(bd, prev.id, ANO, MES, D("-1"))


def test_irs_grava_se_e_fica_na_auditoria(bd, ana):
    marcar(bd, ana, EXEMPLO)
    assert (
        "irs_por_preencher"
        in salarios.folha_do_trabalhador(bd, ana, ANO, MES).folha.chaves_de_alerta()
    )

    salarios.gravar_irs(bd, ana.id, ANO, MES, D("35.50"))
    f = salarios.folha_do_trabalhador(bd, ana, ANO, MES)
    assert f.irs == D("35.50")
    assert f.folha.linha(fs.IRS).total == D("-35.50")
    assert "irs_por_preencher" not in f.folha.chaves_de_alerta()

    registos = bd.scalars(select(Auditoria).where(Auditoria.entidade == "folha_mes")).all()
    assert len(registos) == 1
    assert "35.50" in registos[0].valor_novo

    # gravar o mesmo valor não cria outro registo; apagar volta a «por preencher»
    salarios.gravar_irs(bd, ana.id, ANO, MES, D("35.50"))
    assert bd.scalar(select(func.count()).select_from(Auditoria)) == 1
    salarios.gravar_irs(bd, ana.id, ANO, MES, None)
    assert salarios.folha_do_trabalhador(bd, ana, ANO, MES).irs is None


def test_irs_negativo_e_recusado(bd, ana):
    with pytest.raises(ValueError, match="positivo"):
        salarios.gravar_irs(bd, ana.id, ANO, MES, D("-1"))


def test_mes_fechado_nao_deixa_alterar_a_folha(bd, ana):
    horas = linha_ger(bd, ana, "Banco de horas", "hora", D("8.125"))
    bd.add(FechoMes(empresa_id=ana.empresa_id, ano=ANO, mes=MES, estado=FECHO_FECHADO))
    bd.commit()
    with pytest.raises(ValueError, match="fechado"):
        salarios.gravar_irs(bd, ana.id, ANO, MES, D("10"))
    with pytest.raises(ValueError, match="fechado"):
        salarios.gravar_quantidade(bd, horas.id, ANO, MES, D("2"))
    # outro mês continua aberto
    salarios.gravar_irs(bd, ana.id, ANO, 10, D("10"))


def test_cadeado_de_outra_pessoa_nao_deixa_alterar(bd, ana):
    bloqueios.definir(bd, [ana.id], programa="outro-programa")
    with pytest.raises(bloqueios.Bloqueado):
        salarios.gravar_irs(bd, ana.id, ANO, MES, D("10"))


def test_lancamentos_do_mes_entram_depois_do_liquido(bd, ana):
    marcar(bd, ana, EXEMPLO)
    bd.add_all(
        [
            LancamentoManual(
                trabalhador_id=ana.id,
                ano=ANO,
                mes=MES,
                tipo="adiantamento",
                descricao="07/nov",
                valor=D("-65"),
            ),
            LancamentoManual(
                trabalhador_id=ana.id,
                ano=ANO,
                mes=10,
                tipo="adiantamento",
                descricao="outubro",
                valor=D("-500"),
            ),
        ]
    )
    bd.commit()
    salarios.gravar_irs(bd, ana.id, ANO, MES, D("0"))
    folha = salarios.folha_do_trabalhador(bd, ana, ANO, MES).folha
    assert [m.descricao for m in folha.movimentos] == ["Adiantamento: 07/nov"]
    assert folha.liquido == D("260.96")
    assert folha.a_pagar == D("195.96")


def test_folhas_do_mes_da_empresa(bd, ana):
    outra = Empresa(nome="Outra, Lda")
    bd.add(outra)
    bd.flush()
    bd.add_all(
        [
            Trabalhador(numero=2, nome="De outra empresa", empresa_id=outra.id),
            Trabalhador(numero=3, nome="Inativo sem nada", empresa_id=ana.empresa_id, ativo=False),
            Trabalhador(
                numero=4, nome="Já saiu", empresa_id=ana.empresa_id, data_saida=date(2026, 6, 30)
            ),
            Trabalhador(
                numero=5, nome="Inativo com marcações", empresa_id=ana.empresa_id, ativo=False
            ),
        ]
    )
    bd.commit()
    quinto = bd.scalars(select(Trabalhador).where(Trabalhador.numero == 5)).one()
    marcar(bd, quinto, {2: "P"})
    folhas = salarios.folhas_do_mes(bd, ana.empresa_id, ANO, MES)
    assert [f.numero for f in folhas] == [1, 5]


def test_linhas_ger_habituais_so_para_quem_nao_tem_nenhuma(bd, ana):
    linha_ger(bd, ana, "Combinada à parte", "dia", D("10"))
    rui = Trabalhador(numero=2, nome="Rui Exemplo", empresa_id=ana.empresa_id)
    bd.add(rui)
    bd.commit()
    outros = [rui]
    assert salarios.criar_linhas_habituais(bd, ana.empresa_id) == 1
    assert salarios.criar_linhas_habituais(bd, ana.empresa_id) == 0  # não repete

    da_ana = bd.scalars(select(LinhaGer).where(LinhaGer.trabalhador_id == ana.id)).all()
    assert [x.nome for x in da_ana] == ["Combinada à parte"]
    novas = bd.scalars(
        select(LinhaGer).where(LinhaGer.trabalhador_id == outros[0].id).order_by(LinhaGer.ordem)
    ).all()
    assert [x.nome for x in novas] == [x[0] for x in salarios.LINHAS_GER_HABITUAIS]
    assert all(x.valor is None for x in novas)  # os valores escrevem-se na ficha
    # Sem valor e sem quantidade a folha não fica por calcular; com quantidade, dá erro.
    f = salarios.folha_do_trabalhador(bd, outros[0], ANO, MES)
    assert len(f.folha.linhas_ger) == 6 and f.folha.total_ger == 0
    assert "ger_sem_valor" not in f.folha.chaves_de_alerta()
    salarios.gravar_quantidade(bd, novas[1].id, ANO, MES, D("3"))
    f = salarios.folha_do_trabalhador(bd, outros[0], ANO, MES)
    assert "ger_sem_valor" in f.folha.chaves_de_alerta()


def test_quantidade_ger_contada_das_presencas(bd, ana):
    marcar(bd, ana, {2: "P", 3: "PF", 4: "PF", 5: "PR", 6: "FE", 9: "FI"})
    todos = linha_ger(
        bd, ana, "Aj. geral", "dia", D("210"), base=GER_MENSAL, quantidade_de="trabalho", ordem=1
    )
    linha_ger(bd, ana, "Aj. FR", "dia", D("1500"), base=GER_MENSAL, quantidade_de="franca", ordem=2)
    f = salarios.folha_do_trabalhador(bd, ana, ANO, MES)
    assert [(x.descricao, x.quantidade, x.total) for x in f.folha.linhas_ger] == [
        ("Aj. geral", D("4"), D("40.00")),  # P, PF, PF e PR
        ("Aj. FR", D("2"), D("142.86")),  # só os dois dias em França
    ]
    assert [manual for _, manual in f.linhas_ger] == [False, False]
    with pytest.raises(ValueError, match="grelha de presenças"):
        salarios.gravar_quantidade(bd, todos.id, ANO, MES, D("9"))


def test_quantidade_ger_contada_por_codigos(bd, ana):
    marcar(bd, ana, {2: "P", 3: "PF", 4: "PF", 5: "PR", 7: "DF", 8: "DF", 9: "FI"})
    noites = linha_ger(
        bd, ana, "Desloq", "noite", D("15"), quantidade_de="codigos", codigos="pf;  df,PF", ordem=1
    )
    f = salarios.folha_do_trabalhador(bd, ana, ANO, MES)
    assert [(x.descricao, x.quantidade, x.total) for x in f.folha.linhas_ger] == [
        ("Desloq", D("4"), D("60.00"))  # dois PF e dois DF; o PF repetido conta uma vez
    ]
    assert [manual for _, manual in f.linhas_ger] == [False]
    assert not {"ger_sem_codigos", "ger_codigo_desconhecido"} & f.folha.chaves_de_alerta()
    with pytest.raises(ValueError, match="grelha de presenças"):
        salarios.gravar_quantidade(bd, noites.id, ANO, MES, D("9"))


def test_linha_por_codigos_sem_codigos_ou_com_codigo_apagado_avisa(bd, ana):
    marcar(bd, ana, {2: "PF"})
    linha = linha_ger(bd, ana, "Desloq", "noite", D("15"), quantidade_de="codigos")
    f = salarios.folha_do_trabalhador(bd, ana, ANO, MES)
    assert f.folha.linhas_ger[0].quantidade == 0
    assert "ger_sem_codigos" in f.folha.chaves_de_alerta()
    linha.codigos = "PF, XX"
    bd.commit()
    f = salarios.folha_do_trabalhador(bd, ana, ANO, MES)
    assert f.folha.linhas_ger[0].quantidade == 1
    assert "ger_codigo_desconhecido" in f.folha.chaves_de_alerta()


def test_validar_linha_ger_arruma_e_recusa_codigos_que_nao_existem(bd, ana):
    linha = linha_ger(bd, ana, "Desloq", "noite", D("15"), quantidade_de="codigos")
    linha.codigos = " pf ;df "
    salarios.validar_linha_ger(bd, linha)
    assert linha.codigos == "PF, DF"
    linha.codigos = "PF, ZZ"
    with pytest.raises(ValueError, match="«ZZ» não existe"):
        salarios.validar_linha_ger(bd, linha)
    linha.codigos = "  "
    salarios.validar_linha_ger(bd, linha)
    assert linha.codigos is None


def test_quantidade_ger_das_horas_extra_da_grelha(bd, ana):
    marcar(bd, ana, {2: "P", 3: "P", 7: "P"})
    for m in bd.scalars(select(Marcacao)):
        m.horas_extra = {2: D("2"), 3: D("0"), 7: D("5.5")}[m.data.day]
    bd.commit()
    linha_ger(bd, ana, "Banco de horas", "hora", D("8.125"), quantidade_de="horas")
    f = salarios.folha_do_trabalhador(bd, ana, ANO, MES)
    assert [(x.quantidade, x.total) for x in f.folha.linhas_ger] == [(D("7.5"), D("60.94"))]
    assert [manual for _, manual in f.linhas_ger] == [False]
