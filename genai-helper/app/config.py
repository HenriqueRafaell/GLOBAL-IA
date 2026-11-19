"""Configuração do genai-helper, lida de variáveis de ambiente / arquivo .env.

Nada de modelo ou chave fica hardcoded no código de negócio: tudo passa por aqui.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # pasta genai-helper/

# Modelos padrão (confira os nomes atuais em https://openrouter.ai/models)
DEFAULT_MODEL = "openai/gpt-4o-mini"
DEFAULT_FALLBACKS = "nvidia/nemotron-3.5-super-vl:free,google/gemma-4-31b-it:free"


def _bool(valor: str | None, padrao: bool) -> bool:
    if valor is None or valor.strip() == "":
        return padrao
    return valor.strip().lower() in {"1", "true", "sim", "yes", "on"}


def _lista(valor: str | None) -> list[str]:
    if not valor:
        return []
    return [v.strip() for v in valor.split(",") if v.strip()]


@dataclass
class Settings:
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_mode: str = "openrouter"  # "openrouter" | "mock"
    llm_model: str = DEFAULT_MODEL
    llm_fallback_models: list[str] = field(default_factory=lambda: _lista(DEFAULT_FALLBACKS))
    llm_temperature: float = 0.2
    llm_max_tokens: int = 700
    llm_timeout_s: float = 30.0
    llm_max_retries: int = 2  # novas tentativas por modelo, além da primeira
    llm_backoff_base_s: float = 1.0  # backoff exponencial: base * 2**tentativa
    llm_json_mode: bool = True  # envia response_format={"type":"json_object"}
    app_url: str = "https://github.com/HenriqueRafaell/GLOBAL-IA"  # header HTTP-Referer
    app_title: str = "genai-helper CitizenTech"  # header X-Title
    operador_token: str = ""  # se definido, exigido em X-Operador-Token para aprovar/rejeitar
    log_level: str = "INFO"

    @property
    def modelos(self) -> list[str]:
        """Modelo principal seguido dos fallbacks, sem duplicatas."""
        vistos: list[str] = []
        for m in [self.llm_model, *self.llm_fallback_models]:
            if m and m not in vistos:
                vistos.append(m)
        return vistos

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(BASE_DIR / ".env", override=False)
        env = os.environ.get
        return cls(
            openrouter_api_key=env("OPENROUTER_API_KEY", "").strip(),
            openrouter_base_url=env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            llm_mode=env("LLM_MODE", "openrouter").strip().lower(),
            llm_model=env("LLM_MODEL", DEFAULT_MODEL).strip(),
            llm_fallback_models=_lista(env("LLM_FALLBACK_MODELS", DEFAULT_FALLBACKS)),
            llm_temperature=float(env("LLM_TEMPERATURE", "0.2")),
            llm_max_tokens=int(env("LLM_MAX_TOKENS", "700")),
            llm_timeout_s=float(env("LLM_TIMEOUT_S", "30")),
            llm_max_retries=int(env("LLM_MAX_RETRIES", "2")),
            llm_backoff_base_s=float(env("LLM_BACKOFF_BASE_S", "1.0")),
            llm_json_mode=_bool(env("LLM_JSON_MODE"), True),
            app_url=env("APP_URL", "https://github.com/HenriqueRafaell/GLOBAL-IA"),
            app_title=env("APP_TITLE", "genai-helper CitizenTech"),
            operador_token=env("OPERADOR_TOKEN", "").strip(),
            log_level=env("LOG_LEVEL", "INFO"),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
