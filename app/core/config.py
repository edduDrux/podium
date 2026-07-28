from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração central da API, carregada de variáveis de ambiente / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- Aplicação ---
    PROJECT_NAME: str = "PODIUM API"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # --- Banco de Dados ---
    DATABASE_URL: str = "postgresql+asyncpg://podium:podium@localhost:5432/podium"

    # --- CORS (o Cliente VR em Unity não usa CORS, mas ferramentas web sim) ---
    BACKEND_CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["*"])

    # --- IA: Google Gemini (free tier) ---
    # O Gemini expõe DUAS interfaces e o PODIUM usa as duas:
    #   * LLM  -> endpoint compatível com OpenAI (o SDK `openai` funciona direto).
    #   * STT  -> API nativa, porque o Gemini NÃO tem /audio/transcriptions (Whisper).
    GEMINI_API_KEY: str = ""
    LLM_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    GEMINI_API_BASE: str = "https://generativelanguage.googleapis.com/v1beta"
    LLM_MODEL: str = "gemini-flash-latest"
    STT_MODEL: str = "gemini-flash-latest"

    # A tarefa da banca é extrair e cobrar o que está no material, não variar
    # criativamente — e criatividade, aqui, se manifesta como invenção.
    LLM_TEMPERATURE: float = 0.3
    # Similaridade mínima (0-100) entre o trecho citado pelo LLM e o texto real do slide
    # para a pergunta ser aceita. Alto o bastante para exigir cópia, tolerante o bastante
    # para o ruído de extração (quebras de linha, espaços, aspas tipográficas).
    GROUNDING_MIN_SCORE: int = 90

    # Áudio é enviado inline (base64) ao Gemini; o limite da requisição é ~20 MB.
    MAX_INLINE_AUDIO_MB: int = 18
    AI_TIMEOUT_SECONDS: int = 300

    # --- Armazenamento temporário dos uploads do Cliente VR ---
    STORAGE_DIR: str = "storage"
    MAX_UPLOAD_SIZE_MB: int = 25
    MAX_AUDIO_DURATION_MINUTES: int = 15
    # Retenção dos arquivos de sessão. 0 desativa a limpeza automática.
    STORAGE_RETENTION_HOURS: int = 24
    CLEANUP_INTERVAL_MINUTES: int = 60

    @property
    def storage_path(self) -> Path:
        path = Path(self.STORAGE_DIR)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def max_upload_size_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Instância única (cacheada) das configurações."""
    return Settings()


settings = get_settings()
