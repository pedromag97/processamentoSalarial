"""folha de salário: duodécimos, linhas GER, valores do mês e taxa de Segurança Social

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-19 12:30:00
"""
from alembic import op
import sqlalchemy as sa
import lsc_presencas.modelos


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None

# Como os códigos base contam na folha (igual a dados_base.FOLHA_POR_CODIGO nesta data).
FOLHA_POR_CODIGO = {
    'P': 'trabalho',
    'PF': 'trabalho',
    'PR': 'trabalho',
    'FE': 'ferias',
    'FI': 'falta',
    'B': 'baixa',
    'AT': 'baixa',
}


def upgrade() -> None:
    op.create_table('linha_ger',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('trabalhador_id', sa.Integer(), nullable=False),
    sa.Column('ordem', sa.Integer(), nullable=False),
    sa.Column('nome', sa.String(length=80), nullable=False),
    sa.Column('unidade', sa.String(length=12), nullable=False),
    sa.Column('valor', lsc_presencas.modelos.Valor(length=24), nullable=True),
    sa.Column('base', sa.String(length=10), nullable=False),
    sa.Column('quantidade_de', sa.String(length=10), nullable=False),
    sa.Column('ativo', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['trabalhador_id'], ['trabalhador.id'], name=op.f('fk_linha_ger_trabalhador_id_trabalhador')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_linha_ger'))
    )
    with op.batch_alter_table('linha_ger', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_linha_ger_trabalhador_id'), ['trabalhador_id'], unique=False)

    op.create_table('quantidade_ger',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('linha_ger_id', sa.Integer(), nullable=False),
    sa.Column('ano', sa.Integer(), nullable=False),
    sa.Column('mes', sa.Integer(), nullable=False),
    sa.Column('quantidade', lsc_presencas.modelos.Valor(length=24), nullable=False),
    sa.ForeignKeyConstraint(['linha_ger_id'], ['linha_ger.id'], name=op.f('fk_quantidade_ger_linha_ger_id_linha_ger')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_quantidade_ger')),
    sa.UniqueConstraint('linha_ger_id', 'ano', 'mes', name=op.f('uq_quantidade_ger_linha_ger_id'))
    )
    op.create_table('folha_mes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('trabalhador_id', sa.Integer(), nullable=False),
    sa.Column('ano', sa.Integer(), nullable=False),
    sa.Column('mes', sa.Integer(), nullable=False),
    sa.Column('irs', lsc_presencas.modelos.Valor(length=24), nullable=True),
    sa.ForeignKeyConstraint(['trabalhador_id'], ['trabalhador.id'], name=op.f('fk_folha_mes_trabalhador_id_trabalhador')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_folha_mes')),
    sa.UniqueConstraint('trabalhador_id', 'ano', 'mes', name=op.f('uq_folha_mes_trabalhador_id'))
    )
    with op.batch_alter_table('salario_base', schema=None) as batch_op:
        batch_op.add_column(sa.Column('duodecimo_ferias', lsc_presencas.modelos.Valor(length=24), nullable=True))
        batch_op.add_column(sa.Column('duodecimo_natal', lsc_presencas.modelos.Valor(length=24), nullable=True))

    with op.batch_alter_table('parametros_empresa', schema=None) as batch_op:
        batch_op.add_column(sa.Column('taxa_seguranca_social', lsc_presencas.modelos.Valor(length=24), nullable=True))

    with op.batch_alter_table('codigo_presenca', schema=None) as batch_op:
        batch_op.add_column(sa.Column('conta_folha', sa.String(length=10), server_default='', nullable=False))

    codigo = sa.table('codigo_presenca', sa.column('codigo', sa.String), sa.column('conta_folha', sa.String))
    for nome, conta in FOLHA_POR_CODIGO.items():
        op.execute(codigo.update().where(codigo.c.codigo == nome).values(conta_folha=conta))


def downgrade() -> None:
    with op.batch_alter_table('codigo_presenca', schema=None) as batch_op:
        batch_op.drop_column('conta_folha')

    with op.batch_alter_table('parametros_empresa', schema=None) as batch_op:
        batch_op.drop_column('taxa_seguranca_social')

    with op.batch_alter_table('salario_base', schema=None) as batch_op:
        batch_op.drop_column('duodecimo_natal')
        batch_op.drop_column('duodecimo_ferias')

    op.drop_table('folha_mes')
    op.drop_table('quantidade_ger')
    with op.batch_alter_table('linha_ger', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_linha_ger_trabalhador_id'))
    op.drop_table('linha_ger')
