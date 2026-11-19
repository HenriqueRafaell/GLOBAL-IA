"""Prompts versionados.

Cada prompt é um arquivo `<nome>_<versao>.md` nesta pasta. Para evoluir um
prompt, crie `<nome>_v2.md` e mude a versão em VERSOES — a versão usada vai
junto em `meta.prompt_versao` de cada resposta, o que permite comparar versões.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PASTA = Path(__file__).resolve().parent

VERSOES: dict[str, str] = {
    "chat_system": "v1",
    "boletim_system": "v1",
    "reparo_json": "v1",
    "encurtar_sms": "v1",
}


def versao(nome: str) -> str:
    return f"{nome}_{VERSOES[nome]}"


@lru_cache
def carregar_prompt(nome: str) -> str:
    return (PASTA / f"{versao(nome)}.md").read_text(encoding="utf-8").strip()
