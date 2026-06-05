"""
This is the centralised settings for the project.

Sub-models
----------
DatabaseSettings -> MySQL async connection
RedisSettings -> Redis / Celery broker
LLMSettings -> Groq model tiers
SecuritySettings -> JWT, session, rate-limit
ObservabilitySettings -> Langfuse + LangSmith tracing
"""
from __future__ import annotations
from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.logger import logging
from app.exception import CustomException


class DatabaseSettings(BaseSettings):
    """MySQL connection settings (asyncmy driver)."""

    model_config = SettingsConfigDict(
        env_file = ".env",
        env_file_encoding = "utf-8",
        extra = "ignore",
    )

    DATABASE_URL: str = Field(
        ...,
        description = (
            "Full async DSN, e.g. "
            "mysql+asyncmy://user:pass@host:3306/db_name"
        ),
    )

    # SQLAlchemy async engine pool tuning
    DB_POOL_SIZE: int = Field(default = 10, ge = 1, le = 50)
    DB_MAX_OVERFLOW: int = Field(default = 20, ge = 0, le = 100)
    DB_POOL_RECYCLE_SECONDS: int = Field(default = 3600)
    DB_ECHO_SQL: bool = Field(
        default = False,
        description = "Set True only in local dev to log every SQL statement. Otherwise keep false.",
    )

    @computed_field  # type: ignore[misc]
    @property
    def DATABASE_URL_ASYNC(self) -> str:
        """
        Ensures the driver prefix is 'mysql+asyncmy'.
        Accepts a plain 'mysql://' or 'mysql+mysqlconnector://' DSN from .env
        and normalises it so SQLAlchemy's async engine always gets the right driver.
        """
        url = self.DATABASE_URL
        if url.startswith("mysql+asyncmy://"):
            return url

        # Replace any other mysql driver prefix
        if "://" in url:
            logging.warning(
                f"Expected mysql+asyncmy but got other prefix: {url} "
                "from Class DatabaseSettings Method DATABASE_URL_ASYNC. Normalising to mysql+asyncmy."
            )
            _, rest = url.split("://", 1)
            return f"mysql+asyncmy://{rest}"

        raise CustomException(
            error_message = f"Unrecognised DATABASE_URL format: {url!r}",
            error_detail = "The provided database URL does not contain a valid scheme prefix.",
        )

    @computed_field  # type: ignore[misc]
    @property
    def DATABASE_URL_SYNC(self) -> str:
        """
        Sync DSN for Alembic migrations (uses pymysql).
        Alembic's env.py should call get_settings().db.DATABASE_URL_SYNC.
        """
        async_url = self.DATABASE_URL_ASYNC
        return async_url.replace("mysql+asyncmy://", "mysql+pymysql://")


class RedisSettings(BaseSettings):
    """Redis connection and Celery broker settings."""

    model_config = SettingsConfigDict(
        env_file = ".env",
        env_file_encoding = "utf-8",
        extra = "ignore",
    )

    REDIS_URL: str = Field(
        ...,
        description = "Full Redis DSN including password, e.g. redis://:pass@redis:6379/0",
    )
    REDIS_PASSWORD: str = Field(
        default = "",
        description = "Redis AUTH password (used separately by aioredis clients).",
    )
    CELERY_BROKER_URL: str = Field(
        ...,
        description = "Celery broker DSN (typically Redis DB 1).",
    )

    # Redis connection pool
    REDIS_MAX_CONNECTIONS: int = Field(default = 20, ge = 1)
    REDIS_SOCKET_TIMEOUT: float = Field(default = 5.0)
    REDIS_SOCKET_CONNECT_TIMEOUT: float = Field(default = 2.0)

    # Session / Cache TTLs
    SESSION_TTL_MINUTES: int = Field(
        default = 30,
        ge = 5,
        le = 1440,
        description = "Idle session TTL in minutes before Redis evicts it.",
    )
    REDIS_HISTORY_WINDOW: int = Field(
        default = 20,
        ge = 5,
        le = 100,
        description = "Max number of messages kept in the Redis sliding window per session.",
    )

    @model_validator(mode = "after")
    def _validate_redis_urls(self) -> "RedisSettings":
        """Ensure Redis connection strings use the expected scheme and raise clear errors otherwise."""
        if not self.REDIS_URL.startswith(("redis://", "rediss://")):
            logging.error(
                f"Invalid REDIS_URL scheme: {self.REDIS_URL}. Must start with redis:// or rediss://."
            )
            raise CustomException(
                error_message = "REDIS_URL must start with 'redis://' or 'rediss://'.",
                error_detail = "Invalid URL scheme provided for Redis.",
            )

        if not self.CELERY_BROKER_URL.startswith(("redis://", "rediss://", "amqp://")):
            logging.warning(
                "CELERY_BROKER_URL does not start with redis://, rediss://, or amqp://. "
                "Ensure you are using a valid broker string."
            )
        return self
    

class LLMSettings(BaseSettings):
    """
    Groq-based tiered LLM configuration.

    Tier 1: FAST (Supervisor / intent routing)
        Low latency, cheap, used on every single message.

    Tier 2: CAPABLE (Sub-agent reasoning, tool selection, slot filling)
        Stronger reasoning, used inside individual agents.

    Tier 3: HEAVY (Complex medical synthesis, medication queries)
        Largest model, invoked only when depth is needed.
    """

    model_config = SettingsConfigDict(
        env_file = ".env",
        env_file_encoding = "utf-8",
        extra = "ignore",
    )

    GROQ_API_KEY: str = Field(..., description = "Groq API key (free tier supported).")
    HUGGINGFACE_API_KEY: str | None = Field(default = None, description = "HuggingFace API Key for embeddings.")

    GROQ_BASE_URL: str = Field(
        default = "https://api.groq.com/openai/v1",
        description = "Groq OpenAI-compatible base URL.",
    )
    
    OLLAMA_BASE_URL: str | None = Field(
        default = None,
        description = "Base URL for local Ollama instances.",
    )

    # Tier 1: Fast LLM used for Routing
    LLM_FAST_MODEL: str = Field(
        default = "llama-3.1-8b-instant",
        description = "Groq model for Supervisor intent classification.",
    )
    LLM_FAST_MAX_TOKENS: int = Field(default = 512)
    LLM_FAST_TEMPERATURE: float = Field(default = 0.0, ge = 0.0, le = 2.0)

    # Capable / Agentic
    LLM_CAPABLE_MODEL: str = Field(
        default = "llama-3.3-70b-versatile",
        description = "Groq model for sub-agent reasoning and tool selection.",
    )
    LLM_CAPABLE_MAX_TOKENS: int = Field(default = 1024)
    LLM_CAPABLE_TEMPERATURE: float = Field(default = 0.1, ge = 0.0, le = 2.0)

    # Tier 3: Heavy / Complex Used for medical doc
    LLM_HEAVY_MODEL: str = Field(
        default = "llama-3.3-70b-versatile",
        description = (
            "Groq model for complex synthesis (medication, medical info). "
            "Can be swapped to a Groq preview model when available."
        ),
    )
    LLM_HEAVY_MAX_TOKENS: int = Field(default = 2048)
    LLM_HEAVY_TEMPERATURE: float = Field(default = 0.2, ge = 0.0, le = 2.0)

    # Embeddings (ChromaDB / RAG)
    EMBEDDING_MODEL: str = Field(
        default = "sentence-transformers/all-MiniLM-L6-v2",
        description = "HuggingFace model ID for sentence embeddings (RAG).",
    )

    # Shared Groq settings
    LLM_REQUEST_TIMEOUT: float = Field(
        default = 30.0,
        description = "HTTP timeout in seconds for all Groq API calls.",
    )

    LLM_MAX_RETRIES: int = Field(
        default = 3,
        ge = 0,
        le = 10,
        description = "Number of retry attempts on transient Groq API errors.",
    )

    @model_validator(mode = "after")
    def _warn_if_key_looks_like_placeholder(self) -> "LLMSettings":
        if self.GROQ_API_KEY.startswith("YOUR_") or len(self.GROQ_API_KEY) < 10:
            logging.warning(
                "GROQ_API_KEY looks like a placeholder. "
                "Set a real key in .env before running agents."
            )
        return self


class SecuritySettings(BaseSettings):
    """JWT, session, and rate-limiting settings."""

    model_config = SettingsConfigDict(
        env_file = ".env",
        env_file_encoding = "utf-8",
        extra = "ignore",
    )

    JWT_SECRET_KEY: str = Field(
        ...,
        min_length = 32,
        description = "Random hex string for signing JWTs. Generate with: openssl rand -hex 32",
    )
    JWT_ALGORITHM: str = Field(default = "HS256")
    JWT_EXPIRY_MINUTES: int = Field(
        default = 15,
        ge = 5,
        le = 1440,
        description = "Patient-session JWT TTL in minutes.",
    )

    # Rate limiting (applied by middleware)
    RATE_LIMIT_PER_MINUTE: int = Field(
        default = 60,
        ge = 1,
        description = "Max requests per IP per minute (emergency endpoint is exempt).",
    )
    RATE_LIMIT_PER_SESSION: int = Field(
        default = 30,
        ge = 1,
        description = "Max messages per session before forcing session refresh.",
    )

    # CORS
    ALLOWED_ORIGINS: list[str] = Field(
        default = ["http://localhost:3000", "http://localhost:8000"],
        description = "List of allowed CORS origins.",
    )

    # Appointment booking guardrails
    MIN_BOOKING_ADVANCE_HOURS: int = Field(
        default = 2,
        description = "Minimum hours in advance a patient must book an appointment.",
    )
    MAX_ACTIVE_APPOINTMENTS_PER_PATIENT_PER_DOCTOR: int = Field(
        default = 1,
        description = "Max simultaneous active appointments with the same doctor.",
    )

    # Audit retention
    AUDIT_RETENTION_YEARS: int = Field(
        default = 7,
        description = "How long audit logs are retained (healthcare compliance).",
    )

    @model_validator(mode = "after")
    def _check_jwt_secret_placeholder(self) -> "SecuritySettings":
        """Warn if the JWT secret looks like a template value."""
        key = self.JWT_SECRET_KEY
        if (
            key.startswith("YOUR_")
            or "changeme" in key.lower()
            or key == "4b8c25" * 8   # ✅ fixed: was `key  = =`
            or len(key) < 20
        ):
            logging.warning(
                "JWT_SECRET_KEY appears to be a placeholder or is too short. "
                "Generate a strong key: openssl rand -hex 32"
            )
        return self
    

class ObservabilitySettings(BaseSettings):
    """Langfuse and LangSmith tracing / monitoring settings."""

    model_config = SettingsConfigDict(
        env_file = ".env",
        env_file_encoding = "utf-8",
        extra = "ignore",
    )

    # Langfuse (self-hosted or cloud)
    LANGFUSE_SECRET_KEY: str | None = Field(default = None)
    LANGFUSE_PUBLIC_KEY: str | None = Field(default = None)
    LANGFUSE_BASE_URL: str | None = Field(default = None) 

    # LangSmith
    LANGSMITH_TRACING: bool = Field(default = False)
    LANGSMITH_ENDPOINT: str | None = Field(default = None) 
    LANGSMITH_API_KEY: str | None = Field(default = None)
    LANGSMITH_PROJECT: str = Field(default = "Hospital-Ai-Agent")
    LANGCHAIN_API_KEY: str | None = Field(default = None)

    @computed_field  # type: ignore[misc]
    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.LANGFUSE_SECRET_KEY and self.LANGFUSE_PUBLIC_KEY)

    @computed_field  # type: ignore[misc]
    @property
    def langsmith_enabled(self) -> bool:
        return self.LANGSMITH_TRACING and bool(self.LANGSMITH_API_KEY)

    
    @model_validator(mode = "after")
    def _check_tracing_config(self) -> "ObservabilitySettings":
        """Log warnings when observability services are partially configured."""
        if self.LANGSMITH_TRACING and not self.LANGSMITH_API_KEY:
            logging.warning(
                "LANGSMITH_TRACING is enabled but LANGSMITH_API_KEY is missing. "
                "Traces will not be sent."
            )

        # Langfuse: if either key is present, base URL should also be set
        keys_provided = bool(self.LANGFUSE_SECRET_KEY and self.LANGFUSE_PUBLIC_KEY)
        if keys_provided and not self.LANGFUSE_BASE_URL:
            logging.warning(
                "Langfuse credentials are set but LANGFUSE_BASE_URL is missing. "
                "Tracing may not work correctly."
            )
        return self


# Top Level Settings
class Settings(BaseSettings):
    """
    Root settings object.

    Usage in application code:
        from app.config import get_settings
        s = get_settings()

        # Access sub-models
        s.db.DATABASE_URL_ASYNC
        ...
    """

    model_config = SettingsConfigDict(
        env_file = ".env",
        env_file_encoding = "utf-8",
        extra = "ignore",
    )

    # App identity
    HOSPITAL_NAME: str = Field(default = "City General Hospital")
    APP_VERSION: str = Field(default = "1.0.0")
    ENVIRONMENT: Literal["development", "staging", "production"] = Field(
        default = "development",
    )
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default = "INFO",
    )
    DEBUG: bool = Field(
        default = False,
        description = "Enable FastAPI debug mode. Never True in production.",
    )

    # Composed sub-models
    db: DatabaseSettings = Field(default_factory = DatabaseSettings)
    redis: RedisSettings = Field(default_factory = RedisSettings)
    llm: LLMSettings = Field(default_factory = LLMSettings)
    security: SecuritySettings = Field(default_factory = SecuritySettings)
    obs: ObservabilitySettings = Field(default_factory = ObservabilitySettings)

    # Convenience computed properties
    @computed_field  # type: ignore[misc]
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"   # ✅ fixed: was `= =`

    @computed_field  # type: ignore[misc]
    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"  # ✅ fixed: was `= =`

    @model_validator(mode = "after")
    def _production_safety_checks(self) -> "Settings":
        """Raise hard errors (via CustomException) if obviously unsafe config reaches production."""
        if self.is_production:
            if self.DEBUG:
                logging.error(
                    "Production environment detected but DEBUG is True. Aborting."
                )
                raise CustomException(
                    error_message = "DEBUG must be False in production.",
                    error_detail = "Environment configuration violation.",
                )
            if self.security.JWT_SECRET_KEY.startswith("4b8c25"):
                logging.error(
                    "Production environment detected but JWT_SECRET_KEY is the example key. Aborting."
                )
                raise CustomException(
                    error_message = (
                        "You are using the example JWT_SECRET_KEY in production. "
                        "Generate a new one: openssl rand -hex 32"
                    ),
                    error_detail = "Insecure hardcoded JWT key detected in production.",
                )
        return self

    @model_validator(mode = "after")
    def _log_settings_loaded(self) -> "Settings":
        logging.info(
            f"Settings loaded successfully for environment '{self.ENVIRONMENT}'.",
        )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the cached singleton settings instance."""
    return Settings()