"""Cliente LLM para o OpenRouter (API compatível com OpenAI Chat Completions).

Responsabilidades:
- montar a requisição (modelo, temperatura, max_tokens, response_format, headers);
- retry com backoff exponencial para timeout / 429 / 5xx / erro de rede;
- troca para o(s) modelo(s) de fallback quando o principal esgota as tentativas;
- modo mock (LLM_MODE=mock) para testes sem chave e sem internet;
- devolver metadados: modelo_usado, tentativas, latencia_ms, fallback.

A validação do JSON NÃO acontece aqui (ver app/structured.py).
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

import httpx

from .config import Settings
from .logs import log_evento


# --------------------------------------------------------------------------- #
# Erros
# --------------------------------------------------------------------------- #
class LLMError(Exception):
    """Base."""


class LLMTransientError(LLMError):
    """Vale tentar de novo (timeout, 429, 5xx, rede, resposta vazia)."""


class LLMPermanentError(LLMError):
    """Não adianta repetir no mesmo modelo (400, 401, 403, 404...). Vai para o fallback."""


class LLMUnavailable(LLMError):
    """Nenhum modelo respondeu. Carrega os metadados acumulados."""

    def __init__(self, motivo: str, tentativas: int = 0, latencia_ms: int = 0, ultimo_erro: str = ""):
        super().__init__(motivo)
        self.motivo = motivo
        self.tentativas = tentativas
        self.latencia_ms = latencia_ms
        self.ultimo_erro = ultimo_erro


@dataclass
class LLMResult:
    texto: str
    modelo_usado: str
    tentativas: int
    latencia_ms: int
    fallback: bool


# Assinatura do respondedor mock: (task, messages, model) -> texto  (ou levanta LLMError)
MockResponder = Callable[[str, list[dict], str], str]


@dataclass
class _Chamada:
    task: str
    modelo: str
    messages: list[dict]
    resposta: Optional[str] = None
    erro: Optional[str] = None


class LLMClient:
    def __init__(
        self,
        settings: Settings,
        mock_responder: Optional[MockResponder] = None,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.settings = settings
        self._sleep = sleep
        self._mock = mock_responder
        if settings.llm_mode == "mock" and self._mock is None:
            from .mock_responder import responder_padrao

            self._mock = responder_padrao
        self._http = httpx.Client(timeout=settings.llm_timeout_s, transport=transport)
        # histórico curto das últimas chamadas (usado pelo script de evidências)
        self.historico: deque[_Chamada] = deque(maxlen=20)

    # ------------------------------------------------------------------ #
    @property
    def modo(self) -> str:
        return self.settings.llm_mode

    def complete(self, messages: list[dict], task: str = "geral") -> LLMResult:
        """Chama o LLM com retry + fallback. Levanta LLMUnavailable se tudo falhar."""
        s = self.settings
        if s.llm_mode != "mock" and not s.openrouter_api_key:
            log_evento("llm_sem_chave", task=task)
            raise LLMUnavailable("OPENROUTER_API_KEY ausente")

        modelos = s.modelos
        tentativas = 0
        inicio = time.perf_counter()
        ultimo_erro = ""

        for idx_modelo, modelo in enumerate(modelos):
            for tentativa in range(s.llm_max_retries + 1):
                tentativas += 1
                chamada = _Chamada(task=task, modelo=modelo, messages=messages)
                self.historico.append(chamada)
                try:
                    texto = self._chamar(messages, modelo, task)
                    if not texto or not texto.strip():
                        raise LLMTransientError("resposta vazia do modelo")
                    chamada.resposta = texto
                    latencia = int((time.perf_counter() - inicio) * 1000)
                    log_evento(
                        "llm_ok", task=task, modelo=modelo, tentativas=tentativas,
                        latencia_ms=latencia, fallback=idx_modelo > 0, tamanho_resposta=len(texto),
                    )
                    return LLMResult(texto, modelo, tentativas, latencia, idx_modelo > 0)
                except LLMTransientError as e:
                    ultimo_erro = str(e)
                    chamada.erro = ultimo_erro
                    log_evento("llm_erro_transitorio", task=task, modelo=modelo, tentativa=tentativa + 1, erro=ultimo_erro)
                    if tentativa < s.llm_max_retries:
                        self._sleep(s.llm_backoff_base_s * (2**tentativa))
                except LLMPermanentError as e:
                    ultimo_erro = str(e)
                    chamada.erro = ultimo_erro
                    log_evento("llm_erro_permanente", task=task, modelo=modelo, erro=ultimo_erro)
                    break  # não repete este modelo; vai para o próximo
            if idx_modelo + 1 < len(modelos):
                log_evento("llm_fallback", task=task, de=modelo, para=modelos[idx_modelo + 1])

        latencia = int((time.perf_counter() - inicio) * 1000)
        log_evento("llm_indisponivel", task=task, tentativas=tentativas, latencia_ms=latencia, erro=ultimo_erro)
        raise LLMUnavailable("todos os modelos falharam", tentativas, latencia, ultimo_erro)

    # ------------------------------------------------------------------ #
    def _chamar(self, messages: list[dict], modelo: str, task: str) -> str:
        if self.settings.llm_mode == "mock":
            return self._mock(task, messages, modelo)
        return self._chamar_openrouter(messages, modelo, usar_json_mode=self.settings.llm_json_mode)

    def _chamar_openrouter(self, messages: list[dict], modelo: str, usar_json_mode: bool) -> str:
        s = self.settings
        payload: dict = {
            "model": modelo,
            "messages": messages,
            "temperature": s.llm_temperature,
            "max_tokens": s.llm_max_tokens,
        }
        if usar_json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {s.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": s.app_url,  # recomendado pelo OpenRouter
            "X-Title": s.app_title,  # recomendado pelo OpenRouter
        }
        try:
            r = self._http.post(f"{s.openrouter_base_url}/chat/completions", json=payload, headers=headers)
        except httpx.TimeoutException as e:
            raise LLMTransientError(f"timeout: {type(e).__name__}") from e
        except httpx.TransportError as e:
            raise LLMTransientError(f"erro de rede: {type(e).__name__}") from e

        if r.status_code == 429 or r.status_code >= 500:
            raise LLMTransientError(f"HTTP {r.status_code}")
        if r.status_code >= 400:
            corpo = r.text[:300]
            # alguns modelos não suportam response_format: tenta de novo sem ele
            if usar_json_mode and r.status_code == 400 and "response_format" in corpo:
                return self._chamar_openrouter(messages, modelo, usar_json_mode=False)
            raise LLMPermanentError(f"HTTP {r.status_code}")

        try:
            dados = r.json()
        except ValueError as e:
            raise LLMTransientError("corpo da resposta não é JSON") from e
        # o OpenRouter pode devolver 200 com um objeto "error"
        if isinstance(dados, dict) and dados.get("error"):
            codigo = dados["error"].get("code") if isinstance(dados["error"], dict) else None
            if codigo in (429, 500, 502, 503, 504, None):
                raise LLMTransientError(f"erro do provedor: {codigo}")
            raise LLMPermanentError(f"erro do provedor: {codigo}")
        try:
            return dados["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError) as e:
            raise LLMTransientError("formato de resposta inesperado") from e

    def close(self) -> None:
        self._http.close()
