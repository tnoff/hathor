"""Podcast image: the stored artwork, relative to the podcast directory

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-09
"""
# pylint: disable=no-member,invalid-name,missing-function-docstring
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('podcast') as batch:
        batch.add_column(sa.Column('image', sa.String(length=10240), nullable=True))


def downgrade():
    with op.batch_alter_table('podcast') as batch:
        batch.drop_column('image')
