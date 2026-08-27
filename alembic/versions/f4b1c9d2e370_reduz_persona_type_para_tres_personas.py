"""reduz persona_type para tres personas (remove plateia_leiga)

Revision ID: f4b1c9d2e370
Revises: e8732f4eb5c9
Create Date: 2026-08-08 03:58:12.104553

Escrita à mão: o autogenerate não detecta remoção de valor de ENUM, e o Postgres não
remove um valor in-place (`ALTER TYPE ... DROP VALUE` não existe). O caminho é recriar o
tipo e reapontar a coluna.

Sobre linhas existentes: o `USING` faz o cast valor a valor. Se alguma sessão tiver sido
gravada com PLATEIA_LEIGA, o cast falha e a migration aborta inteira (DDL transacional no
Postgres) — deliberado. Regravar essas sessões com outra persona falsificaria o registro
de qual banca realmente gerou aquelas perguntas, e esse registro é dado de validação do
TCC. Verificado antes de escrever: `SELECT persona, count(*) FROM presentations` devolveu
0 linhas.

Atenção ao rodar em outro banco: o SQLAlchemy grava o NOME do membro do enum
("PLATEIA_LEIGA"), não o valor ("plateia_leiga") — é por isso que os labels aqui estão em
maiúsculas.
"""
from collections.abc import Sequence

from alembic import op


revision: str = 'f4b1c9d2e370'
down_revision: str | None = 'e8732f4eb5c9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERSONAS_TRES = ('PROFESSOR_RIGOROSO', 'ORIENTADOR_ACOLHEDOR', 'ESPECIALISTA_TECNICO')
PERSONAS_QUATRO = PERSONAS_TRES + ('PLATEIA_LEIGA',)


def _trocar_tipo(labels: tuple[str, ...]) -> None:
    """Recria `persona_type` com os labels dados e reaponta `presentations.persona`.

    O tipo antigo é renomeado em vez de removido primeiro: a coluna ainda depende dele
    enquanto o novo não estiver no lugar.
    """
    valores = ", ".join(f"'{label}'" for label in labels)

    op.execute("ALTER TYPE persona_type RENAME TO persona_type_antigo")
    op.execute(f"CREATE TYPE persona_type AS ENUM ({valores})")
    op.execute(
        "ALTER TABLE presentations "
        "ALTER COLUMN persona TYPE persona_type "
        "USING persona::text::persona_type"
    )
    op.execute("DROP TYPE persona_type_antigo")


def upgrade() -> None:
    _trocar_tipo(PERSONAS_TRES)


def downgrade() -> None:
    _trocar_tipo(PERSONAS_QUATRO)
