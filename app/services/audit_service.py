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


async def registrar(
    presentation_id: uuid.UUID,
    etapa: LLMCallStage,
    provider: str,
    modelo: str,
    temperatura: float,
    latencia_ms: int,
    sucesso: bool,
    tokens_entrada: int | None = None,
    tokens_saida: int | None = None,
    erro: str | None = None,
) -> None:
    """Grava uma chamada de IA. Engole qualquer falha, apenas registrando em log."""
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                LLMCall(
                    presentation_id=presentation_id,
                    etapa=etapa,
                    provider=provider,
                    modelo=modelo,
                    temperatura=temperatura,
                    tokens_entrada=tokens_entrada,
                    tokens_saida=tokens_saida,
                    latencia_ms=latencia_ms,
                    sucesso=sucesso,
                    erro=erro,
                )
            )
            await db.commit()
    except Exception:
        logger.exception(
            "Falha ao auditar a chamada de IA (%s) da sessão %s. O pipeline segue.",
            etapa,
            presentation_id,
        )


class AuditoriaBanco:
    """Implementação de `Auditoria` que grava em `llm_calls`.

    É a única peça que conhece o banco nesta cadeia. Os adaptadores de IA recebem esta
    instância pela porta e não sabem onde — nem se — o registro é persistido.
    """

    def medir(
        self,
        presentation_id: uuid.UUID | None,
        etapa: LLMCallStage,
        modelo: str,
        temperatura: float,
    ):
        return medir(presentation_id, etapa, modelo, temperatura)


@asynccontextmanager
async def medir(
    presentation_id: uuid.UUID | None,
    etapa: LLMCallStage,
    modelo: str,
    temperatura: float,
    provider: str = PROVIDER_GEMINI,
):
    """Cronometra o bloco e grava o registro de auditoria, tendo ele falhado ou não.

    Cede um dicionário mutável onde o chamador deposita os tokens assim que a resposta
    chega (`uso["tokens_entrada"] = ...`). É feito assim porque o número de tokens só
    existe depois da chamada, mas o registro precisa sair mesmo quando ela levanta —
    e nesse caso a contagem simplesmente fica nula.

    `presentation_id` nulo desliga a auditoria: permite chamar os serviços fora de uma
    sessão (script, teste manual) sem violar a FK.
    """
    uso: dict[str, int | None] = {"tokens_entrada": None, "tokens_saida": None}
    inicio = time.perf_counter()
    erro: str | None = None

    try:
        yield uso
    except Exception as exc:
        erro = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        latencia_ms = int((time.perf_counter() - inicio) * 1000)
        if presentation_id is not None:
            await registrar(
                presentation_id=presentation_id,
                etapa=etapa,
                provider=provider,
                modelo=modelo,
                temperatura=temperatura,
                latencia_ms=latencia_ms,
                sucesso=erro is None,
                tokens_entrada=uso.get("tokens_entrada"),
                tokens_saida=uso.get("tokens_saida"),
                erro=erro,
            )
