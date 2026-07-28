from enum import StrEnum


class ScenarioType(StrEnum):
    """Cenários VR disponíveis. O MVP entrega apenas a Sala de Aula."""

    SALA_DE_AULA = "sala_de_aula"


class PersonaType(StrEnum):
    """Persona que a banca (LLM) assume ao formular as perguntas."""

    PROFESSOR_RIGOROSO = "professor_rigoroso"
    ORIENTADOR_ACOLHEDOR = "orientador_acolhedor"
    ESPECIALISTA_TECNICO = "especialista_tecnico"
    PLATEIA_LEIGA = "plateia_leiga"


class SourceFileType(StrEnum):
    """Formatos de apresentação aceitos na ingestão (CONTEXTO §2: PDF e PPTx)."""

    PDF = "pdf"
    PPTX = "pptx"


class LLMCallStage(StrEnum):
    """Etapa do pipeline que originou a chamada de IA.

    Separa as duas porque elas têm perfis de custo e latência muito diferentes: o STT
    cresce com a duração do áudio, a geração cresce com o tamanho do material.
    """

    STT = "stt"
    GERACAO_PERGUNTAS = "geracao_perguntas"


class PresentationStatus(StrEnum):
    """Ciclo de vida de uma sessão de apresentação."""

    CREATED = "created"           # sessão criada, PDF recebido e texto extraído
    AUDIO_RECEIVED = "audio_received"
    PROCESSING = "processing"     # STT + LLM em andamento
    COMPLETED = "completed"       # feedback duplo disponível
    FAILED = "failed"
