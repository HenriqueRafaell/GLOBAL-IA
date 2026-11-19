"""Respostas fixas/determinísticas para LLM_MODE=mock.

Permite rodar a API, a página de chat e os testes sem chave e sem internet.
Também oferece `RoteiroMock`, que devolve uma sequência programada de respostas
(inclusive RUINS: texto puro, JSON quebrado, enum inválido, timeout) para
provar o tratamento de falhas.
"""
from __future__ import annotations

import json
import re
from typing import Iterable, Union

from .guardrails import PREFIXO_EMERGENCIA, detectar_emergencia, normalizar
from .llm_client import LLMError


def _ultimo_user(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m["role"] == "user":
            return m["content"]
    return ""


def _primeiro_user(messages: list[dict]) -> str:
    for m in messages:
        if m["role"] == "user":
            return m["content"]
    return ""


def _entre(texto: str, tag: str) -> str:
    # pega o ÚLTIMO bloco: a instrução pode citar as tags antes do bloco de dados
    achados = re.findall(rf"<{tag}>\n(.*?)\n</{tag}>", texto, re.DOTALL)
    return achados[-1] if achados else ""


def _mock_chat(messages: list[dict]) -> str:
    u = _primeiro_user(messages)
    pergunta = _entre(u, "mensagem_cidadao")
    trechos = re.findall(r'<trecho id="([^"]+)"[^>]*>\s*(.*?)\s*</trecho>', u, re.DOTALL)
    emergencia = detectar_emergencia(pergunta)[0] or "emergencia_por_palavra_chave: sim" in u
    if not trechos:
        return json.dumps({
            "resposta": "Desculpe, não tenho essa informação. Eu só ajudo com o aplicativo de alertas. "
                        "Fale com o atendimento humano.",
            "confianca": "baixa", "fontes": [], "precisa_atendimento_humano": True,
            "emergencia_detectada": emergencia,
        }, ensure_ascii=False)
    tid, texto = trechos[0]
    linhas = [l.strip("- ").strip() for l in texto.splitlines() if l.strip()]
    resposta = " ".join(linhas[:4])
    if emergencia:
        resposta = f"{PREFIXO_EMERGENCIA} {resposta}"
    return json.dumps({
        "resposta": resposta, "confianca": "media", "fontes": [tid],
        "precisa_atendimento_humano": emergencia, "emergencia_detectada": emergencia,
    }, ensure_ascii=False)


_TIPOS = [
    ("onda_de_calor", r"onda de calor|temperatura|calor"),
    ("deslizamento", r"deslizamento|escorregamento|movimento de massa"),
    ("enchente", r"enchente|inundac|transbord|cheia"),
    ("alagamento", r"alagamento|alagad"),
    ("tempestade", r"tempestade|chuva|temporal|vendaval"),
]
_RE_PERIGO = re.compile(r"\bperigo\b(?! potencial)")
_RE_NIVEL_ALTO = re.compile(r"(nivel|risco)[^\n]{0,25}\balto\b")
_RE_MUNICIPIOS = re.compile(r"munic[ií]pios?(?:\(s\))?(?: afetados)?\s*:\s*([^\n.]+)", re.IGNORECASE)
_RE_BAIRROS = re.compile(r"bairros?(?: com maior risco)?\s*:\s*([^\n.]+)", re.IGNORECASE)


def _lista(m: re.Match | None) -> list[str]:
    return [x.strip() for x in re.split(r",| e ", m.group(1)) if x.strip()] if m else []


def _mock_boletim(messages: list[dict]) -> str:
    """Extrator por regras: imita o LLM o suficiente para a demo e os testes."""
    texto = _entre(_primeiro_user(messages), "boletim")
    t = normalizar(texto)
    tipo = next((nome for nome, rx in _TIPOS if re.search(rx, t)), "outro")
    if "grande perigo" in t or "vermelho" in t or "muito alto" in t:
        sev = "extrema"
    elif _RE_PERIGO.search(t) or "laranja" in t or _RE_NIVEL_ALTO.search(t):
        sev = "alta"
    elif "perigo potencial" in t or "amarelo" in t or "moderado" in t:
        sev = "moderada"
    else:
        sev = "baixa"
    fonte = "INMET" if "inmet" in t else "Cemaden" if "cemaden" in t else "Defesa Civil" if "defesa civil" in t else "outra"
    municipios = _lista(_RE_MUNICIPIOS.search(texto))
    bairros = _lista(_RE_BAIRROS.search(texto))
    regioes = [{"municipio": mu, "bairros": bairros if i == 0 else []} for i, mu in enumerate(municipios)]
    nome_tipo = tipo.replace("_", " ")
    locais = ", ".join(municipios) or "sua regiao"
    return json.dumps({
        "tipo_evento": tipo, "severidade": sev, "regioes_afetadas": regioes,
        "inicio": None, "fim": None, "fonte": fonte,
        "recomendacoes": ["Fique atento aos avisos da Defesa Civil.", "Em perigo, procure um lugar seguro."],
        "mensagem_sms": f"ALERTA {nome_tipo} ({sev}) em {locais}. Fique atento e procure local seguro. Emergencia: 199",
        "mensagem_whatsapp": f"ALERTA de {nome_tipo}, nivel {sev}, em {locais}. Fique atento aos avisos oficiais. "
                             "Em emergência ligue 199 (Defesa Civil) ou 193 (Bombeiros).",
        "confianca": "media" if municipios and tipo != "outro" else "baixa",
    }, ensure_ascii=False)


def _mock_encurtar(messages: list[dict]) -> str:
    from .guardrails import truncar_sms

    sms = _entre(_ultimo_user(messages), "sms")
    return json.dumps({"mensagem_sms": truncar_sms(sms)}, ensure_ascii=False)


def responder_padrao(task: str, messages: list[dict], model: str) -> str:
    base = task.split(":")[0]
    if base == "chat":
        return _mock_chat(messages)
    if base == "boletim":
        return _mock_boletim(messages)
    if base == "encurtar_sms":
        return _mock_encurtar(messages)
    return "{}"


Item = Union[str, LLMError, Exception]


class RoteiroMock:
    """Respondedor programável: cada chamada consome o próximo item.

    - str: devolvido como texto do modelo;
    - exceção: levantada (ex.: LLMTransientError('timeout') simula timeout).
    Registra todas as chamadas em `self.chamadas` para inspeção nos testes.
    Quando o roteiro acaba, usa `responder_padrao`.
    """

    def __init__(self, itens: Iterable[Item] = ()):
        self.itens = list(itens)
        self.chamadas: list[dict] = []

    def __call__(self, task: str, messages: list[dict], model: str) -> str:
        self.chamadas.append({"task": task, "messages": messages, "model": model})
        if self.itens:
            item = self.itens.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        return responder_padrao(task, messages, model)
