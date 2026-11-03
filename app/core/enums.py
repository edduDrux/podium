from enum import StrEnum


class ScenarioType(StrEnum):
    """Cenários VR disponíveis. O MVP entrega apenas a Sala de Aula."""

    CLASSROOM = "classroom"


class PersonaType(StrEnum):
    """Persona que a banca (LLM) assume ao formular as perguntas.

    Três, e não quatro: cada persona é uma superfície de prompt que precisa ser validada
    e reportada no TCC, e a `plateia_leiga` ficou fora do escopo avaliado (migration
    `f4b1c9d2e370`). Reduzir o escopo é reduzir o que se promete ter medido.
    """

    STRICT_PROFESSOR = "strict_professor"
    SUPPORTIVE_ADVISOR = "supportive_advisor"
    TECHNICAL_EXPERT = "technical_expert"


class SourceFileType(StrEnum):
    """Formatos de apresentação aceitos na ingestão (CONTEXTO §2: PDF e PPTx)."""

    PDF = "pdf"
    PPTX = "pptx"


class PairingStatus(StrEnum):
    """Situação de um código de pareamento: esperando o arquivo ou com ele recebido."""

    WAITING = "waiting"
    RECEIVED = "received"


class LLMCallStage(StrEnum):
    """Etapa do pipeline que originou a chamada de IA.

    Separa as duas porque elas têm perfis de custo e latência muito diferentes: o STT
    cresce com a duração do áudio, a geração cresce com o tamanho do material.
    """

    STT = "stt"
    QUESTION_GENERATION = "question_generation"


class PresentationStatus(StrEnum):
    """Ciclo de vida de uma sessão de apresentação."""

    CREATED = "created"  # sessão criada, PDF recebido e texto extraído
    AUDIO_RECEIVED = "audio_received"
    PROCESSING = "processing"  # STT + LLM em andamento
    COMPLETED = "completed"  # feedback duplo disponível
    FAILED = "failed"


class AnalysisMode(StrEnum):
    """Quanto da apresentação a análise cobre.

    `full` cruza slides e fala (cobertura, perguntas ancoradas no slide ou na fala) e
    exige áudio; `basic` analisa só o que foi dito — sem slides no prompt e sem
    cobertura — e aceita a transcrição do headset, o áudio ou os dois (DECISOES §11).
    """

    BASIC = "basic"
    FULL = "full"
