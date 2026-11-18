"""cadeados nos funcionários

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-18 18:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('bloqueio_trabalhador',
    sa.Column('trabalhador_id', sa.Integer(), nullable=False),
    sa.Column('utilizador', sa.String(length=80), nullable=False),
    sa.Column('nome', sa.String(length=120), nullable=False),
    sa.Column('programa', sa.String(length=32), nullable=False),
    sa.Column('desde', sa.DateTime(), nullable=False),
    sa.Column('renovado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['trabalhador_id'], ['trabalhador.id'], name=op.f('fk_bloqueio_trabalhador_trabalhador_id_trabalhador')),
    sa.PrimaryKeyConstraint('trabalhador_id', name=op.f('pk_bloqueio_trabalhador'))
    )
    with op.batch_alter_table('bloqueio_trabalhador', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_bloqueio_trabalhador_programa'), ['programa'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('bloqueio_trabalhador', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_bloqueio_trabalhador_programa'))
    op.drop_table('bloqueio_trabalhador')
