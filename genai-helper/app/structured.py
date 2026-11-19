"""Saída estruturada: extrair JSON da resposta do modelo, validar com Pydantic
e, se falhar, fazer UMA chamada de reparo enviando o erro de validação.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Generic, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from .llm_client import LLMClient, LLMUnavailable
from .logs import log_evento
from .prompts import carregar_prompt
from .schemas import Meta

T = TypeVar("T", bound=BaseModel)

_CERCA = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)


def extrair_json(texto: str) -> Optional[dict]:
    """Tenta obter um objeto JSON de uma resposta que pode ter cercas markdown,
    texto antes/depois ou vários blocos. Retorna None se não houver objeto válido."""
    if not texto:
        return None
    t = texto.strip()
    candidatos = [t]
    candidatos += [m.strip() for m in _CERCA.findall(t)]
    for c in candidatos:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass
    # procura o primeiro objeto decodificável a partir de cada "{"
    dec = json.JSONDecoder()
    for i, ch in enumerate(t):
        if ch == "{":
            try:
                obj, _ = dec.raw_decode(t[i:])
                if isinstance(obj, dict):
                    return obj
            except ValueError:
                continue
    return None


def resumir_erros(e: ValidationError) -> str:
    partes = []
    for err in e.errors()[:8]:
        local = ".".join(str(x) for x in err.get("loc", ())) or "(raiz)"
        partes.append(f"- campo '{local}': {err.get('msg')}")
    return "\n".join(partes)


def validar(texto: str, modelo: Type[T]) -> tuple[Optional[T], str]:
    obj = extrair_json(texto)
    if obj is None:
        return None, "- a resposta não contém um objeto JSON válido"
    try:
        return modelo.model_validate(obj), ""
    except ValidationError as e:
        return None, resumir_erros(e)


class RespostaInvalida(Exception):
    def __init__(self, erro: str, meta: Meta):
        super().__init__(erro)
        self.erro = erro
        self.meta = meta


@dataclass
class Resultado(Generic[T]):
    dados: T
    meta: Meta


def meta_de_falha(e: Exception, prompt_versao: str | None = None) -> Meta:
    if isinstance(e, RespostaInvalida):
        m = e.meta.model_copy()
    elif isinstance(e, LLMUnavailable):
        m = Meta(tentativas=e.tentativas, latencia_ms=e.latencia_ms)
    else:
        m = Meta()
    m.resposta_segura = True
    m.prompt_versao = m.prompt_versao or prompt_versao
    return m


def chamar_estruturado(
    client: LLMClient,
    task: str,
    messages: list[dict],
    modelo: Type[T],
    prompt_versao: str | None = None,
) -> Resultado[T]:
    """Chama o LLM e devolve o objeto validado. Levanta LLMUnavailable ou RespostaInvalida."""
    r1 = client.complete(messages, task=task)
    meta = Meta(
        modelo_usado=r1.modelo_usado, tentativas=r1.tentativas, latencia_ms=r1.latencia_ms,
        fallback=r1.fallback, prompt_versao=prompt_versao,
    )
    dados, erro = validar(r1.texto, modelo)
    if dados is not None:
        return Resultado(dados, meta)

    # ---- UMA tentativa de reparo -------------------------------------- #
    log_evento("json_invalido", task=task, modelo=r1.modelo_usado, erro=erro[:200])
    schema = json.dumps(modelo.model_json_schema(), ensure_ascii=False)
    reparo = (
        carregar_prompt("reparo_json")
        .replace("{{ERROS}}", erro)
        .replace("{{SCHEMA}}", schema)
    )
    msgs = [*messages, {"role": "assistant", "content": r1.texto[:4000]}, {"role": "user", "content": reparo}]
    try:
        r2 = client.complete(msgs, task=f"{task}:reparo")
    except LLMUnavailable as e:
        meta.tentativas += e.tentativas
        raise RespostaInvalida(erro, meta) from e
    meta.tentativas += r2.tentativas
    meta.latencia_ms += r2.latencia_ms
    meta.reparo_json = True
    meta.modelo_usado = r2.modelo_usado
    meta.fallback = meta.fallback or r2.fallback

    dados, erro2 = validar(r2.texto, modelo)
    if dados is not None:
        log_evento("json_reparado", task=task, modelo=r2.modelo_usado)
        return Resultado(dados, meta)
    log_evento("json_reparo_falhou", task=task, modelo=r2.modelo_usado, erro=erro2[:200])
    raise RespostaInvalida(erro2, meta)
