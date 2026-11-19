"""Logs estruturados (JSON por linha) SEM dados pessoais.

Regra: nunca logar o texto do cidadão nem o texto do boletim; apenas eventos,
modelos, contagens, tamanhos e tempos.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

_logger = logging.getLogger("genai_helper")
if not _logger.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_h)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False

# chaves que nunca devem aparecer em log, mesmo que alguém passe por engano
_CHAVES_PROIBIDAS = {"mensagem", "texto", "prompt", "messages", "conteudo", "telefone", "cpf", "email"}


def log_evento(evento: str, nivel: int = logging.INFO, **campos) -> None:
    seguros = {k: v for k, v in campos.items() if k not in _CHAVES_PROIBIDAS}
    registro = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "evento": evento, **seguros}
    _logger.log(nivel, json.dumps(registro, ensure_ascii=False, default=str))


def configurar_nivel(nivel: str) -> None:
    _logger.setLevel(getattr(logging, nivel.upper(), logging.INFO))
