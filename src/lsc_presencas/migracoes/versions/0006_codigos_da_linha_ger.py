"""linhas GER: códigos de presença a contar (quantidade vinda da grelha)

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-20 10:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('linha_ger', schema=None) as batch_op:
        batch_op.add_column(sa.Column('codigos', sa.String(length=120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('linha_ger', schema=None) as batch_op:
        batch_op.drop_column('codigos')
