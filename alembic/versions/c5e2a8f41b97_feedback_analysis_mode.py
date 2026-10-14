"""adiciona feedbacks.analysis_mode (analise basica ou completa)

Revision ID: c5e2a8f41b97
Revises: 3d9a6f2c8b14
Create Date: 2026-10-13 10:00:00.000000

Coluna própria, e não chave do JSONB `metrics`: o modo é a dimensão pela qual o relatório
compara latência e qualidade das análises, e filtrar por coluna é direto (DECISOES §11).

Os feedbacks existentes recebem 'FULL' pelo `server_default`: todos foram análises
completas, a única que existia. O SQLAlchemy grava o NOME do membro do enum ("FULL"),
não o valor ("full") — por isso os labels aqui estão em maiúsculas.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c5e2a8f41b97"
down_revision: str | None = "3d9a6f2c8b14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANALYSIS_MODE = sa.Enum("BASIC", "FULL", name="analysis_mode")


def upgrade() -> None:
    ANALYSIS_MODE.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "feedbacks",
        sa.Column("analysis_mode", ANALYSIS_MODE, server_default="FULL", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("feedbacks", "analysis_mode")
    ANALYSIS_MODE.drop(op.get_bind(), checkfirst=True)
