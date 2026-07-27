"""pptx support: rename pdf_* to file_* and add file_type

Revision ID: 76acc52e4337
Revises: 0441e47cf078
Create Date: 2026-07-24 00:44:32.328218

O autogenerate propôs drop+add, o que descartaria os dados existentes e violaria o
NOT NULL nas linhas já gravadas. Trocado por um RENAME real das colunas.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '76acc52e4337'
down_revision: str | None = '0441e47cf078'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


source_file_type = sa.Enum('PDF', 'PPTX', name='source_file_type')


def upgrade() -> None:
    op.alter_column('presentations', 'pdf_path', new_column_name='file_path')
    op.alter_column('presentations', 'pdf_filename', new_column_name='file_filename')

    # As sessões que já existem foram todas criadas a partir de PDF.
    source_file_type.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'presentations',
        sa.Column(
            'file_type',
            source_file_type,
            nullable=False,
            server_default='PDF',
        ),
    )
    op.alter_column('presentations', 'file_type', server_default=None)


def downgrade() -> None:
    op.drop_column('presentations', 'file_type')
    source_file_type.drop(op.get_bind(), checkfirst=True)

    op.alter_column('presentations', 'file_filename', new_column_name='pdf_filename')
    op.alter_column('presentations', 'file_path', new_column_name='pdf_path')
