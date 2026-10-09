"""Baseline: the schema hathor created before migrations existed

Revision ID: 0001
Revises:
Create Date: 2026-10-09
"""
# pylint: disable=no-member,invalid-name,missing-function-docstring
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'podcast',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=True),
        sa.Column('archive_type', sa.String(), nullable=False),
        sa.Column('broadcast_id', sa.String(), nullable=False),
        sa.Column('max_allowed', sa.Integer(), nullable=True),
        sa.Column('file_location', sa.String(length=10240), nullable=True),
        sa.Column('artist_name', sa.String(length=256), nullable=True),
        sa.Column('automatic_episode_download', sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('archive_type', 'broadcast_id', name='_broadcast_indentifier'),
        sa.UniqueConstraint('name'),
    )
    op.create_table(
        'podcast_episode',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('download_url', sa.String(length=10240), nullable=True),
        sa.Column('processed_url', sa.String(length=10240), nullable=True),
        sa.Column('title', sa.String(length=10240), nullable=True),
        sa.Column('description', sa.String(length=10240), nullable=True),
        sa.Column('date', sa.DateTime(), nullable=True),
        sa.Column('podcast_id', sa.Integer(), nullable=True),
        sa.Column('file_path', sa.String(length=10240), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('prevent_deletion', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['podcast_id'], ['podcast.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('download_url'),
    )
    op.create_table(
        'podcast_title_filter',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('podcast_id', sa.Integer(), nullable=True),
        sa.Column('regex_string', sa.String(length=2048), nullable=False),
        sa.ForeignKeyConstraint(['podcast_id'], ['podcast.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('podcast_id', 'regex_string', name='_repeating_filters'),
    )


def downgrade():
    op.drop_table('podcast_title_filter')
    op.drop_table('podcast_episode')
    op.drop_table('podcast')
