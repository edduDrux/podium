"""renomeia para ingles colunas, valores de ENUM e chaves do JSONB

Revision ID: 3d9a6f2c8b14
Revises: f4b1c9d2e370
Create Date: 2026-10-12 18:00:00.000000

Escrita à mão (CLAUDE.md §8). O autogenerate proporia drop + add das colunas da
`llm_calls`, e isso apagaria as chamadas medidas que alimentam o capítulo de validação do
TCC. Aqui nada é recriado: `alter_column(new_column_name=...)`, `ALTER INDEX ... RENAME`
e `ALTER TYPE ... RENAME VALUE` renomeiam no lugar, e as chaves do JSONB de `feedbacks`
são convertidas linha a linha. O `downgrade` faz o caminho inverso com os mesmos mapas.

Atenção: o SQLAlchemy grava o NOME do membro do enum ("PROFESSOR_RIGOROSO"), não o valor
("professor_rigoroso") — por isso os labels aqui estão em maiúsculas.

Verificado antes de escrever (banco local, 2026-10-12): 27 linhas em `llm_calls`, 16 em
`presentations`, 9 em `feedbacks`; chaves do JSONB `aterramento`, `contexto`, `cobertura`
e `transcricao`; perguntas com `slide_origem` e `trecho_literal`.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "3d9a6f2c8b14"
down_revision: str | None = "f4b1c9d2e370"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


LLM_CALL_COLUMNS = {
    "etapa": "stage",
    "modelo": "model",
    "temperatura": "temperature",
    "tokens_entrada": "input_tokens",
    "tokens_saida": "output_tokens",
    "latencia_ms": "latency_ms",
    "sucesso": "success",
    "erro": "error",
    "criado_em": "created_at",
}
LLM_CALL_INDEXES = {
    "ix_llm_calls_etapa": "ix_llm_calls_stage",
    "ix_llm_calls_sucesso": "ix_llm_calls_success",
}
ENUM_LABELS = {
    "persona_type": {
        "PROFESSOR_RIGOROSO": "STRICT_PROFESSOR",
        "ORIENTADOR_ACOLHEDOR": "SUPPORTIVE_ADVISOR",
        "ESPECIALISTA_TECNICO": "TECHNICAL_EXPERT",
    },
    "scenario_type": {"SALA_DE_AULA": "CLASSROOM"},
    "llm_call_stage": {"GERACAO_PERGUNTAS": "QUESTION_GENERATION"},
}

# Chaves de primeiro nível do JSONB `feedbacks.metrics`; as métricas de forma
# (`word_count`, `duration_seconds`...) já estavam em inglês.
METRICS_KEYS = {
    "aterramento": "grounding",
    "contexto": "context",
    "cobertura": "slide_coverage",
    "transcricao": "transcript_source",
}
GROUNDING_KEYS = {
    "perguntas_geradas": "questions_generated",
    "perguntas_aprovadas": "questions_approved",
}
CONTEXT_KEYS = {
    "slides_truncados": "slides_truncated",
    "transcricao_truncada": "transcript_truncated",
}
COVERAGE_KEYS = {"percentual_coberto": "coverage_ratio", "alerta_descolamento": "mismatch_alert"}
COVERAGE_SLIDE_KEYS = {
    "numero": "slide_number",
    "classificacao": "classification",
    "termos_totais": "total_terms",
    "termos_presentes": "present_terms",
    "termos_ausentes": "missing_terms",
}
CLASSIFICATIONS = {
    "apresentado": "presented",
    "parcial": "partial",
    "nao_apresentado": "not_presented",
    "sem_termos": "no_terms",
}
TRANSCRIPT_SOURCE_KEYS = {"origem": "origin", "motor": "engine"}
ORIGINS = {"cliente_vr": "vr_client", "servidor": "server"}
QUESTION_KEYS = {"slide_origem": "slide_number", "trecho_literal": "quote"}

FEEDBACKS = sa.table(
    "feedbacks",
    sa.column("id", sa.Uuid),
    sa.column("metrics", JSONB),
    sa.column("questions", JSONB),
)


def _inverted(mapping: dict[str, str]) -> dict[str, str]:
    return {new: old for old, new in mapping.items()}


def _renamed(data: dict[str, Any], keys: dict[str, str]) -> dict[str, Any]:
    return {keys.get(key, key): value for key, value in data.items()}


def _convert_metrics(metrics: dict[str, Any], forward: bool) -> dict[str, Any]:
    """Renomeia as chaves do JSONB de métricas e os valores que são códigos.

    `forward` escolhe a direção: os mesmos mapas servem ao upgrade e ao downgrade, para
    que os dois caminhos não divirjam.
    """

    def keys(mapping: dict[str, str]) -> dict[str, str]:
        return mapping if forward else _inverted(mapping)

    def converted(mapping: dict[str, str], pt_key: str) -> str:
        """Nome que a chave `pt_key` tem DEPOIS desta conversão."""
        return mapping[pt_key] if forward else pt_key

    result = _renamed(metrics, keys(METRICS_KEYS))

    grounding = converted(METRICS_KEYS, "aterramento")
    if isinstance(result.get(grounding), dict):
        result[grounding] = _renamed(result[grounding], keys(GROUNDING_KEYS))

    context = converted(METRICS_KEYS, "contexto")
    if isinstance(result.get(context), dict):
        result[context] = _renamed(result[context], keys(CONTEXT_KEYS))

    coverage = converted(METRICS_KEYS, "cobertura")
    if isinstance(result.get(coverage), dict):
        report = _renamed(result[coverage], keys(COVERAGE_KEYS))
        label = converted(COVERAGE_SLIDE_KEYS, "classificacao")
        slides = []
        for slide in report.get("slides") or []:
            slide = _renamed(slide, keys(COVERAGE_SLIDE_KEYS))
            slide[label] = keys(CLASSIFICATIONS).get(slide.get(label), slide.get(label))
            slides.append(slide)
        report["slides"] = slides
        result[coverage] = report

    source = converted(METRICS_KEYS, "transcricao")
    if isinstance(result.get(source), dict):
        origin = _renamed(result[source], keys(TRANSCRIPT_SOURCE_KEYS))
        origin_key = converted(TRANSCRIPT_SOURCE_KEYS, "origem")
        origin[origin_key] = keys(ORIGINS).get(origin.get(origin_key), origin.get(origin_key))
        result[source] = origin

    return result


def _convert_feedbacks(forward: bool) -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(FEEDBACKS.c.id, FEEDBACKS.c.metrics, FEEDBACKS.c.questions)
    ).all()
    question_keys = QUESTION_KEYS if forward else _inverted(QUESTION_KEYS)

    for row in rows:
        connection.execute(
            sa.update(FEEDBACKS)
            .where(FEEDBACKS.c.id == row.id)
            .values(
                metrics=_convert_metrics(row.metrics or {}, forward),
                questions=[_renamed(item, question_keys) for item in row.questions or []],
            )
        )


def _rename_enum_labels(forward: bool) -> None:
    for type_name, labels in ENUM_LABELS.items():
        for old, new in (labels if forward else _inverted(labels)).items():
            op.execute(f"ALTER TYPE {type_name} RENAME VALUE '{old}' TO '{new}'")


def _rename_llm_calls(forward: bool) -> None:
    indexes = LLM_CALL_INDEXES if forward else _inverted(LLM_CALL_INDEXES)
    for old, new in indexes.items():
        op.execute(f"ALTER INDEX {old} RENAME TO {new}")

    columns = LLM_CALL_COLUMNS if forward else _inverted(LLM_CALL_COLUMNS)
    for old, new in columns.items():
        op.alter_column("llm_calls", old, new_column_name=new)


def upgrade() -> None:
    _rename_llm_calls(forward=True)
    _rename_enum_labels(forward=True)
    _convert_feedbacks(forward=True)


def downgrade() -> None:
    _convert_feedbacks(forward=False)
    _rename_enum_labels(forward=False)
    _rename_llm_calls(forward=False)
