"""contas de login

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-18 17:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('utilizador',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nome_utilizador', sa.String(length=40), nullable=False),
    sa.Column('nome', sa.String(length=120), nullable=False),
    sa.Column('perfil', sa.String(length=12), nullable=False),
    sa.Column('ativo', sa.Boolean(), nullable=False),
    sa.Column('senha_hash', sa.String(length=200), nullable=False),
    sa.Column('tentativas_falhadas', sa.Integer(), nullable=False),
    sa.Column('bloqueado_ate', sa.DateTime(), nullable=True),
    sa.Column('ultimo_login', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_utilizador')),
    sa.UniqueConstraint('nome_utilizador', name=op.f('uq_utilizador_nome_utilizador'))
    )


def downgrade() -> None:
    op.drop_table('utilizador')
