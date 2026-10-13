"""Portas: o que o pipeline precisa dos serviços externos, descrito sem citar nenhum.

O orquestrador depende destes protocolos, não das implementações. Isso resolve dois
problemas concretos:

1. **Direção da dependência.** Ao instrumentar a auditoria, os adaptadores de IA passaram
   a importar o serviço de auditoria, que importa o banco — ou seja, para gerar perguntas
   era preciso arrastar o SQLAlchemy junto. Com `Audit` como porta injetada, o
   adaptador declara o que precisa e quem monta o sistema decide o que entregar.

2. **Testar sem infraestrutura.** Um `Transcriber` falso devolve texto fixo e um
   `LanguageModel` falso devolve o JSON que um modelo devolveria, permitindo exercitar o
   pipeline inteiro — inclusive o aterramento — sem rede, sem cota de IA e sem Postgres.

O ponto de troca de cada porta fica onde algo realmente varia. Na banca, o que varia é o
transporte até o modelo (Gemini hoje, outro provedor amanhã, o dublê nos testes); o que
perguntar e o que aceitar da resposta é regra, e mora em `app.domain.panel`. Por isso a
porta é `LanguageModel` (texto entra, texto sai) e não "gere as perguntas": se fosse,
cada provedor teria de reimplementar — e lembrar de chamar — o aterramento.

São `Protocol` e não classes-base: a implementação não precisa herdar nada, basta ter os
métodos. Mantém os adaptadores legíveis e evita hierarquia cerimonial num projeto de um
desenvolvedor só.

São `runtime_checkable` para que um `isinstance` confirme que um dublê de teste implementa
mesmo a porta — a verificação checa a presença dos métodos; as assinaturas, quem confere
é o mypy.
"""

import uuid
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.core.enums import LLMCallStage


@runtime_checkable
class Audit(Protocol):
    """Registro das chamadas de IA para o capítulo de validação técnica."""

    def measure(
        self,
        presentation_id: uuid.UUID | None,
        stage: LLMCallStage,
        model: str,
        temperature: float,
    ) -> AbstractAsyncContextManager[dict[str, int | None]]:
        """Cronometra o bloco e grava o registro, tendo a chamada falhado ou não.

        Cede um dicionário mutável onde o adaptador deposita os tokens quando a resposta
        chega. Gravar auditoria nunca pode derrubar o pipeline: a implementação engole as
        próprias falhas, mas repropaga intacta a exceção de quem foi medido.
        """
        ...


@runtime_checkable
class Transcriber(Protocol):
    """Converte o áudio da apresentação em texto."""

    async def transcribe(
        self,
        audio_path: Path | str,
        language: str = "pt",
        presentation_id: uuid.UUID | None = None,
    ) -> str: ...


@runtime_checkable
class LanguageModel(Protocol):
    """Envia um prompt ao modelo de linguagem e devolve o texto da resposta.

    Devolve `None` quando o provedor não produz resposta nenhuma (chamada barrada pelo
    próprio provedor) — o domínio trata isso como "zero perguntas", que é degradação
    prevista, e não como falha da sessão.
    """

    async def complete(
        self,
        system: str,
        user: str,
        presentation_id: uuid.UUID | None = None,
    ) -> str | None: ...
