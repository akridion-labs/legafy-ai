"""Central runtime configuration.

Every tunable is environment-driven so the same image runs unchanged on a
developer laptop, in CI and on the Akridion custom CPU server.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Typed view over the process environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Service identity ---------------------------------------------------
    env: str = Field(default="development", alias="LEGAFY_ENV")
    host: str = Field(default="0.0.0.0", alias="LEGAFY_HOST")
    port: int = Field(default=8000, alias="LEGAFY_PORT")
    log_level: str = Field(default="INFO", alias="LEGAFY_LOG_LEVEL")
    public_base_url: str = Field(
        default="http://localhost:8000", alias="LEGAFY_PUBLIC_BASE_URL"
    )

    # --- Telemetry / audit vault -------------------------------------------
    telemetry_salt: str = Field(default="", alias="LEGAFY_TELEMETRY_SALT")
    audit_vault_path: str = Field(
        default="generated/akrigon_audit_vault.json", alias="LEGAFY_AUDIT_VAULT_PATH"
    )
    generated_dir: str = Field(default="generated", alias="LEGAFY_GENERATED_DIR")

    # --- Tenancy ------------------------------------------------------------
    license_registry_path: str = Field(
        default="data/license_registry.json", alias="LEGAFY_LICENSE_REGISTRY_PATH"
    )
    bootstrap_tokens_enabled: bool = Field(
        default=True, alias="LEGAFY_BOOTSTRAP_TOKENS_ENABLED"
    )

    # --- Rate limiting ------------------------------------------------------
    ratelimit_backend: str = Field(default="memory", alias="LEGAFY_RATELIMIT_BACKEND")
    redis_url: str = Field(default="redis://redis:6379/0", alias="LEGAFY_REDIS_URL")

    # --- Provider router ----------------------------------------------------
    provider_chain: str = Field(
        default="anthropic,openai,ollama,offline", alias="LEGAFY_PROVIDER_CHAIN"
    )
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-sonnet-4-5", alias="LEGAFY_ANTHROPIC_MODEL")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o", alias="LEGAFY_OPENAI_MODEL")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1", alias="LEGAFY_OPENAI_BASE_URL"
    )
    ollama_base_url: str = Field(
        default="http://host.docker.internal:11434", alias="LEGAFY_OLLAMA_BASE_URL"
    )
    ollama_model: str = Field(default="llama3.1:8b", alias="LEGAFY_OLLAMA_MODEL")

    # --- Chunk-assembly pipeline -------------------------------------------
    chunk_max_tokens: int = Field(default=3000, alias="LEGAFY_CHUNK_MAX_TOKENS")
    chunk_continuations: int = Field(default=4, alias="LEGAFY_CHUNK_CONTINUATIONS")
    chunk_concurrency: int = Field(default=1, alias="LEGAFY_CHUNK_CONCURRENCY")
    min_document_words: int = Field(default=10000, alias="LEGAFY_MIN_DOCUMENT_WORDS")

    # --- Cloudflare ---------------------------------------------------------
    cloudflare_hostname: str = Field(
        default="legal-mcp.akridion.com", alias="CLOUDFLARE_HOSTNAME"
    )

    @field_validator("provider_chain")
    @classmethod
    def _non_empty_chain(cls, value: str) -> str:
        if not [p for p in value.split(",") if p.strip()]:
            raise ValueError("LEGAFY_PROVIDER_CHAIN must name at least one provider")
        return value

    # --- Derived helpers ----------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"production", "prod"}

    @property
    def providers(self) -> list[str]:
        return [p.strip().lower() for p in self.provider_chain.split(",") if p.strip()]

    @property
    def generated_path(self) -> Path:
        path = Path(self.generated_dir)
        if not path.is_absolute():
            path = REPO_ROOT / path
        return path

    @property
    def vault_path(self) -> Path:
        path = Path(self.audit_vault_path)
        if not path.is_absolute():
            path = REPO_ROOT / path
        return path

    @property
    def registry_path(self) -> Path:
        path = Path(self.license_registry_path)
        if not path.is_absolute():
            path = REPO_ROOT / path
        return path

    def validate_production_posture(self) -> list[str]:
        """Return a list of hard failures that must block a production boot."""
        problems: list[str] = []
        if not self.is_production:
            return problems
        if not self.telemetry_salt or self.telemetry_salt.startswith("CHANGE_ME"):
            problems.append(
                "LEGAFY_TELEMETRY_SALT is unset or still the template value; "
                "telemetry pseudonymisation would be trivially reversible."
            )
        if self.bootstrap_tokens_enabled:
            problems.append(
                "LEGAFY_BOOTSTRAP_TOKENS_ENABLED=true is refused in production; "
                "publish a real registry at LEGAFY_LICENSE_REGISTRY_PATH."
            )
        if not self.registry_path.exists():
            problems.append(
                f"Licence registry not found at {self.registry_path}. "
                "Production requires an explicit tenant registry."
            )
        return problems


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Test hook — drops the memoised Settings instance."""
    get_settings.cache_clear()


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
