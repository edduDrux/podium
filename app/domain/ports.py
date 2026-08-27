"""Portas: o que o pipeline precisa dos serviços externos, descrito sem citar nenhum.

O orquestrador depende destes protocolos, não das implementações. Isso resolve dois
problemas concretos:

1. **Direção da dependência.** Ao instrumentar a auditoria, os adaptadores de IA passaram
   a importar o serviço de auditoria, que importa o banco — ou seja, para gerar perguntas
   era preciso arrastar o SQLAlchemy junto. Com `Auditoria` como porta injetada, o
   adaptador declara o que precisa e quem monta o sistema decide o que entregar.

2. **Testar sem infraestrutura.** Um `Transcritor` falso devolve texto fixo e um
   `BancaExaminadora` falso devolve perguntas fixas, permitindo exercitar o pipeline
   inteiro sem rede, sem cota de IA e sem Postgres.

São `Protocol` e não classes-base: a implementação não precisa herdar nada, basta ter os
métodos. Mantém os adaptadores legíveis e evita hierarquia cerimonial num projeto de um
desenvolvedor só.

São `runtime_checkable` para que um `isinstance` confirme que um dublê de teste implementa
mesmo a porta — a verificação checa a presença dos métodos, não as assinaturas, mas pega
o erro mais comum, que é o dublê ficar defasado quando a porta ganha um método.
"""

import uuid
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.core.enums import LLMCallStage, PersonaType
from app.domain.banca import ResultadoGeracao


@runtime_checkable
class Auditoria(Protocol):
    """Registro das chamadas de IA para o capítulo de validação técnica."""

    def medir(
        self,
        presentation_id: uuid.UUID | None,
        etapa: LLMCallStage,
        modelo: str,
        temperatura: float,
    ) -> AbstractAsyncContextManager[dict[str, int | None]]:
        """Cronometra o bloco e grava o registro, tendo a chamada falhado ou não.

        Cede um dicionário mutável onde o adaptador deposita os tokens quando a resposta
        chega. Gravar auditoria nunca pode derrubar o pipeline: a implementação engole as
        próprias falhas, mas repropaga intacta a exceção de quem foi medido.
        """
        ...


@runtime_checkable
class Transcritor(Protocol):
    """Converte o áudio da apresentação em texto."""

    async def transcrever(
        self,
        audio_path: Path | str,
        language: str = "pt",
        presentation_id: uuid.UUID | None = None,
    ) -> str: ...


@runtime_checkable
class BancaExaminadora(Protocol):
    """Formula as perguntas da banca a partir do material e da fala."""

    async def gerar_perguntas(
        self,
        slides_text: str,
        transcript: str,
        persona: PersonaType,
        presentation_id: uuid.UUID | None = None,
    ) -> ResultadoGeracao: ...
