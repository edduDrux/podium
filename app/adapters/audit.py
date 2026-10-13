"""Auditoria das chamadas de IA — instrumentação para o capítulo de validação do TCC.

Este módulo tem uma regra acima de todas: **gravar auditoria nunca pode derrubar o
pipeline**. O usuário não perde o feedback porque o log de métricas falhou.

Daí a escolha de abrir uma sessão de banco própria em vez de reaproveitar a do pipeline:
se o INSERT falhasse dentro da transação do pipeline, a sessão do SQLAlchemy ficaria em
estado inválido e o `commit` do feedback — que já estava pronto — falharia junto. Sessão
separada isola a falha no lugar onde ela nasceu.
"""

import logging
import time
import uuid
from contextlib import asynccontextmanager

from app.core.database import AsyncSessionLocal
from app.core.enums import LLMCallStage
from app.models.llm_call import LLMCall

logger = logging.getLogger(__name__)

PROVIDER_GEMINI = "gemini"


async def register(
    presentation_id: uuid.UUID,
    stage: LLMCallStage,
    provider: str,
    model: str,
    temperature: float,
    latency_ms: int,
    success: bool,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    error: str | None = None,
) -> None:
    """Grava uma chamada de IA. Engole qualquer falha, apenas registrando em log."""
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                LLMCall(
                    presentation_id=presentation_id,
                    stage=stage,
                    provider=provider,
                    model=model,
                    temperature=temperature,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    success=success,
                    error=error,
                )
            )
            await db.commit()
    except Exception:
        logger.exception(
            "Falha ao auditar a chamada de IA (%s) da sessão %s. O pipeline segue.",
            stage,
            presentation_id,
        )


class DatabaseAudit:
    """Implementação de `Audit` que grava em `llm_calls`.

    É a única peça que conhece o banco nesta cadeia. Os adaptadores de IA recebem esta
    instância pela porta e não sabem onde — nem se — o registro é persistido.
    """

    def measure(
        self,
        presentation_id: uuid.UUID | None,
        stage: LLMCallStage,
        model: str,
        temperature: float,
    ):
        return measure(presentation_id, stage, model, temperature)


@asynccontextmanager
async def measure(
    presentation_id: uuid.UUID | None,
    stage: LLMCallStage,
    model: str,
    temperature: float,
    provider: str = PROVIDER_GEMINI,
):
    """Cronometra o bloco e grava o registro de auditoria, tendo ele falhado ou não.

    Cede um dicionário mutável onde o chamador deposita os tokens assim que a resposta
    chega (`usage["input_tokens"] = ...`). É feito assim porque o número de tokens só
    existe depois da chamada, mas o registro precisa sair mesmo quando ela levanta —
    e nesse caso a contagem simplesmente fica nula.

    `presentation_id` nulo desliga a auditoria: permite chamar os serviços fora de uma
    sessão (script, teste manual) sem violar a FK.
    """
    usage: dict[str, int | None] = {"input_tokens": None, "output_tokens": None}
    start = time.perf_counter()
    error: str | None = None

    try:
        yield usage
    # `BaseException`, e não `Exception`: um shutdown ou um restart do `--reload` cancela a
    # tarefa com `CancelledError`, que não herda de `Exception`. Capturando só `Exception`,
    # a chamada interrompida entraria em `llm_calls` como `success=True` e com a latência
    # truncada no instante do cancelamento — contaminando justamente as duas métricas que
    # esta tabela existe para produzir.
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        latency_ms = int((time.perf_counter() - start) * 1000)
        if presentation_id is not None:
            await register(
                presentation_id=presentation_id,
                stage=stage,
                provider=provider,
                model=model,
                temperature=temperature,
                latency_ms=latency_ms,
                success=error is None,
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                error=error,
            )
