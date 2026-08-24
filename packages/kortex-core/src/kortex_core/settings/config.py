"""Application settings.

All settings are loaded from environment variables prefixed with ``KORTEX_``.
Process-wide singleton via :func:`get_settings`. Tests can override by clearing
the lru_cache and re-instantiating.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]

# Defaults that are safe for local dev but must never reach production.
_INSECURE_JWT_SECRET = "dev-only-secret-replace-with-32-random-bytes-base64-encoded"
_INSECURE_S3_CREDENTIAL = "minioadmin"


class KortexSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KORTEX_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: Environment = "development"

    # --- Database ---
    database_url: str = Field(
        default="postgresql+asyncpg://kortex:kortex@localhost:5432/kortex",
        description="Async SQLAlchemy DSN. Must use the asyncpg driver.",
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_echo: bool = False

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- S3 ---
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_bucket: str = "kortex-attachments"
    s3_access_key: SecretStr = SecretStr(_INSECURE_S3_CREDENTIAL)
    s3_secret_key: SecretStr = SecretStr(_INSECURE_S3_CREDENTIAL)
    s3_use_ssl: bool = False

    # --- Blob storage ---
    storage_backend: Literal["s3", "fs"] = "s3"
    fs_storage_root: str = "./.kortex-blobs"

    # --- Web / email ---
    # Base URL of the web SPA, used to build links in emails (reset/verify).
    web_base_url: str = "http://localhost:5173"
    # From-address for outbound mail.
    email_from: str = "no-reply@kortex.dev"
    # Delivery backend: "log" (dev — surfaces links in logs) or "smtp".
    email_backend: Literal["log", "smtp"] = "log"
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True

    # --- Billing (Stripe) ---
    # All optional: when stripe_secret_key is unset, billing runs in "unconfigured"
    # mode — plans still list, but checkout/portal return a clear 503.
    stripe_secret_key: SecretStr | None = None
    stripe_webhook_secret: SecretStr | None = None
    stripe_price_pro: str | None = None
    stripe_price_team: str | None = None
    billing_success_url: str = "http://localhost:5173/app/billing?checkout=success"
    billing_cancel_url: str = "http://localhost:5173/app/billing?checkout=cancel"

    @property
    def billing_enabled(self) -> bool:
        return self.stripe_secret_key is not None

    # --- Attachments ---
    attachment_chunk_tokens: int = 512
    attachment_chunk_overlap: int = 64
    attachment_max_bytes: int = 64 * 1024 * 1024

    # --- Auth ---
    jwt_secret: SecretStr = SecretStr(_INSECURE_JWT_SECRET)
    jwt_algorithm: str = "HS512"
    jwt_access_ttl_seconds: int = 3600
    jwt_refresh_ttl_seconds: int = 60 * 60 * 24 * 30
    api_key_prefix_length: int = 8
    api_key_secret_length: int = 43

    # --- Embeddings ---
    embedder: str = "local_bge"
    embedder_model: str = "BAAI/bge-large-en-v1.5"
    embedder_dim: int = 1024
    embedder_batch_size: int = 64
    embed_max_attempts: int = 5
    """Retries before a memory is parked as failed instead of retried forever."""
    embed_retry_base_seconds: int = 60
    """Exponential backoff base: attempt N waits base * 2^(N-1), capped at an hour."""
    openai_api_key: SecretStr | None = None
    voyage_api_key: SecretStr | None = None
    cohere_api_key: SecretStr | None = None

    # --- LLM ---
    llm_provider: str = "anthropic"
    llm_model_planner: str = "claude-sonnet-4-7"
    llm_model_summarizer: str = "claude-haiku-4-5"
    anthropic_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    ollama_base_url: str = "http://localhost:11434"

    # --- Retrieval ---
    agentic_retrieval: bool = True
    retrieval_max_hops: int = 3
    retrieval_max_candidates: int = 200
    retrieval_top_k_vector: int = 50
    retrieval_top_k_bm25: int = 50
    retrieval_rrf_k: int = 60
    retrieval_default_max_tokens: int = 4000

    # --- Conflict detection (write-path; surfaces stale/contradictory memories) ---
    conflict_detection: bool = True
    conflict_similarity_threshold: float = 0.82
    """Cosine similarity a neighbour must clear before the judge even sees it."""
    conflict_max_candidates: int = 5
    conflict_min_confidence: float = 0.6
    conflict_batch_size: int = 32
    conflict_daily_quota_per_org: int = 2000

    # --- Memory tiers / decay ---
    decay_lambda_short: float = 0.30
    decay_lambda_mid: float = 0.05
    decay_lambda_long: float = 0.005
    decay_short_to_mid_age_hours: int = 24
    decay_short_delete_age_days: int = 7
    decay_short_delete_threshold: float = 0.05
    decay_mid_archive_age_days: int = 180
    decay_mid_archive_threshold: float = 0.10

    # --- Telemetry ---
    otel_enabled: bool = False
    otel_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "kortex"
    log_level: str = "INFO"
    log_json: bool = True

    # --- API ---
    api_host: str = "0.0.0.0"  # noqa: S104  (binding is operator-controlled)
    api_port: int = 8000
    # NoDecode: keep pydantic-settings from JSON-decoding the env value before our
    # validator runs, so a plain comma-separated list (KORTEX_API_CORS_ORIGINS=a,b)
    # works instead of crashing the app at boot.
    api_cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    api_request_max_bytes: int = 16 * 1024 * 1024

    # --- Rate limiting ---
    rate_limit_read_per_min: int = 600
    rate_limit_write_per_min: int = 120
    rate_limit_recall_per_min: int = 30
    # Per-org/day cap on LLM-backed recalls (planner + summarizer + embeddings).
    # This is the cost ceiling: without it a single tenant can drive an unbounded
    # model bill within the per-minute limit. 0 disables the cap.
    recall_daily_quota_per_org: int = 5000

    # --- Optional encryption KEK (for sensitivity=secret bodies) ---
    kms_key: SecretStr | None = None
    kms_provider: Literal["env", "aws"] = "env"

    @field_validator("api_cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            value = [v.strip() for v in value.split(",") if v.strip()]
        # The API sends CORS responses with allow_credentials=True; a "*" origin
        # combined with credentials is a browser footgun (and rejected by browsers
        # anyway), so refuse it outright rather than silently shipping it.
        if isinstance(value, list) and "*" in value:
            raise ValueError(
                "api_cors_origins may not contain '*' (credentialed CORS requires explicit origins)"
            )
        return value

    @model_validator(mode="after")
    def _reject_insecure_production_defaults(self) -> KortexSettings:
        """Fail closed: never boot production with the shipped dev secrets."""
        if not self.is_production:
            return self
        insecure: list[str] = []
        if self.jwt_secret.get_secret_value() == _INSECURE_JWT_SECRET:
            insecure.append("KORTEX_JWT_SECRET")
        if _INSECURE_S3_CREDENTIAL in (
            self.s3_access_key.get_secret_value(),
            self.s3_secret_key.get_secret_value(),
        ):
            insecure.append("KORTEX_S3_ACCESS_KEY/KORTEX_S3_SECRET_KEY")
        if insecure:
            raise ValueError(
                "refusing to start in production with default credentials: "
                + ", ".join(insecure)
                + " are still set to their insecure development defaults."
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache(maxsize=1)
def get_settings() -> KortexSettings:
    """Return the process-wide settings singleton."""
    return KortexSettings()
