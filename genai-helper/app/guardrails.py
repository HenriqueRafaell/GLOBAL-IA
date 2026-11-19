"""Guardrails determinísticos: não dependem do LLM.

- detectar_emergencia: palavras-chave de perigo acontecendo agora.
- mascarar_dados_pessoais: LGPD, antes de qualquer envio ao LLM.
- truncar_sms / truncar_texto: limites de tamanho seguros.
- detectar_injecao / neutralizar_delimitadores: proteção contra prompt injection.
- encontrar_links: links em mensagens de alerta exigem revisão.
"""
from __future__ import annotations

import re
import unicodedata

from .schemas import SMS_LIMITE, WHATSAPP_LIMITE

PREFIXO_EMERGENCIA = "EMERGÊNCIA: ligue agora 199 (Defesa Civil), 193 (Bombeiros) ou 192 (SAMU)."


def normalizar(texto: str) -> str:
    """minúsculas e sem acentos, para casar palavras-chave."""
    t = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


# --------------------------------------------------------------------------- #
# Emergência
# --------------------------------------------------------------------------- #
# Viés de segurança: preferimos falso positivo (mostrar 199 sem necessidade)
# a falso negativo (não mostrar quando a pessoa está em perigo).
_PADROES_EMERGENCIA = [
    r"agua\s+(esta\s+|ta\s+|tá\s+)?(entrando|invadindo|subindo)",
    r"(entrando|entrou|invadiu|invadindo)\s+agua",
    r"(casa|rua|quarto|sala)\s+(esta\s+|ta\s+)?(alagando|alagada|inundando|inundada|enchendo)",
    r"\b(alagou|inundou)\s+(a\s+|minha\s+)?(casa|rua)",
    r"\bilhad[oa]s?\b",
    r"\barrastad[oa]s?\b",
    r"\bcorrenteza\b",
    r"\bafogand[oa]\b",
    r"\bpres[oa]s?\s+(na|no|pela|pelo|em)\b",
    r"\bsocorro\b",
    r"\bajuda\s+urgente\b",
    r"\bdesmai(ou|ado|ada|ando)\b",
    r"\bpassou\s+mal\b",
    r"\bpassando\s+mal\b",
    r"\binconscient[e]s?\b",
    r"\bconvuls",
    r"\bnao\s+(consegue|consigo|esta\s+conseguindo)\s+respirar\b",
    r"\binsolacao\b",
    r"\bdesidratad[oa]\b",
    r"\b(barranco|morro|encosta|muro|terra)\s+(caiu|caindo|desabou|desabando|deslizou|deslizando|cedendo|cedeu)\b",
    r"\b(casa|parede|teto)\s+(caiu|caindo|desabou|desabando|rachando)\b",
    r"\bdeslizamento\s+(agora|aqui|na\s+minha)",
    r"\bferid[oa]s?\b",
    r"\bsoterrad[oa]s?\b",
    r"\bchoque\s+eletrico\b",
    r"\bfio\s+(caido|caiu|solto)\b",
]
_RE_EMERGENCIA = [re.compile(p) for p in _PADROES_EMERGENCIA]


def detectar_emergencia(texto: str) -> tuple[bool, list[str]]:
    t = normalizar(texto)
    achados = [m.group(0) for r in _RE_EMERGENCIA if (m := r.search(t))]
    return bool(achados), achados


def garantir_prefixo_emergencia(resposta: str) -> str:
    if normalizar(resposta).lstrip().startswith(normalizar(PREFIXO_EMERGENCIA)[:20]):
        return resposta
    return f"{PREFIXO_EMERGENCIA} {resposta}".strip()


# --------------------------------------------------------------------------- #
# Mascaramento de dados pessoais (LGPD)
# --------------------------------------------------------------------------- #
_RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_RE_CPF = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")
_RE_CEP = re.compile(r"(?<!\d)\d{5}-\d{3}(?!\d)|(?i:\bcep\b[:\s]*)\d{8}(?!\d)")
_RE_TELEFONE = re.compile(
    r"(?<!\d)(\+?55[\s-]?)?(\(?\d{2}\)?[\s-]?)?9?\d{4}[\s-]?\d{4}(?!\d)"
)
_LOGRADOURO = r"(rua|r\.|avenida|av\.|travessa|tv\.|estrada|alameda|praca|praça|rodovia|viela|beco)"
_RE_NUMERO_CASA = re.compile(
    rf"(?i)(\b{_LOGRADOURO}\s+[^\n,;]{{2,60}}?,?\s*(n[ºo°.]?\s*)?)(\d{{1,5}}[a-zA-Z]?)\b"
)
_RE_NUMERO_SOLTO = re.compile(r"(?i)(\b(n[ºo°]|numero|número|casa)\s*[:.]?\s*)(\d{1,5}[a-zA-Z]?)\b")


def mascarar_dados_pessoais(texto: str, manter_endereco: bool = False) -> tuple[str, dict[str, int]]:
    """Substitui dados pessoais por marcadores. Retorna (texto, contagem por tipo).

    manter_endereco=True preserva CEP e número de logradouro (útil em boletins,
    onde endereço é de área pública afetada, não de uma pessoa).
    """
    contagem: dict[str, int] = {}

    def _sub(regex: re.Pattern, marcador: str, t: str, grupo_prefixo: bool = False) -> str:
        def troca(m: re.Match) -> str:
            contagem[marcador] = contagem.get(marcador, 0) + 1
            return (m.group(1) if grupo_prefixo else "") + f"[{marcador}]"

        return regex.sub(troca, t)

    t = _sub(_RE_EMAIL, "EMAIL", texto)
    t = _sub(_RE_CPF, "CPF", t)
    if not manter_endereco:
        t = _sub(_RE_CEP, "CEP", t)
    t = _sub(_RE_TELEFONE, "TELEFONE", t)
    if not manter_endereco:
        t = _sub(_RE_NUMERO_CASA, "NUMERO", t, grupo_prefixo=True)
        t = _sub(_RE_NUMERO_SOLTO, "NUMERO", t, grupo_prefixo=True)
    return t, contagem


# --------------------------------------------------------------------------- #
# Tamanho de mensagens
# --------------------------------------------------------------------------- #
_SUFIXO_SMS = " Emergencia: 199"


def truncar_texto(texto: str, limite: int, sufixo: str = "") -> str:
    """Corta em limite de palavra, garantindo len(resultado) <= limite."""
    texto = " ".join(texto.split())
    if len(texto) <= limite:
        return texto
    espaco = limite - len(sufixo) - 3  # 3 = "..."
    corte = texto[:espaco]
    if " " in corte:
        corte = corte[: corte.rfind(" ")]
    corte = corte.rstrip(" ,;:.-")
    resultado = f"{corte}...{sufixo}"
    return resultado[:limite]


def truncar_sms(texto: str, limite: int = SMS_LIMITE) -> str:
    """Truncagem segura do SMS: se o corte remover o 199, o sufixo de emergência é recolocado."""
    texto = " ".join(texto.split())
    if len(texto) <= limite:
        return texto
    base = texto.replace("Emergencia: 199", "").replace("Emergência: 199", "").strip()
    return truncar_texto(base, limite, sufixo=_SUFIXO_SMS)


def truncar_whatsapp(texto: str, limite: int = WHATSAPP_LIMITE) -> str:
    texto = texto.strip()
    if len(texto) <= limite:
        return texto
    sufixo = " Em emergência ligue 199." if "199" not in texto[: limite - 30] else ""
    return truncar_texto(texto, limite, sufixo=sufixo)


# --------------------------------------------------------------------------- #
# Prompt injection
# --------------------------------------------------------------------------- #
_PADROES_INJECAO = [
    r"ignor(e|a|ar|em)\s+(todas\s+)?(as\s+)?(suas\s+)?(instrucoes|regras|orientacoes)",
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"desconsider(e|ar)\s+(as\s+)?(instrucoes|regras)",
    r"(system\s+prompt|prompt\s+do\s+sistema)",
    r"voce\s+(agora\s+)?e\s+(um|uma|o|a)\s+",
    r"\b(mude|altere|defina)\s+o\s+status",
    r"status\s*[:=]\s*\"?aprovado",
    r"\b(aprove|envie|dispare)\s+(imediatamente|agora|direto|sem\s+revisao)",
    r"sem\s+(aprovacao|revisao)\s+(humana)?",
    r"(responda|retorne)\s+(apenas|somente)\s+",
    r"</?\s*(boletim|system|instrucoes)\s*>",
]
_RE_INJECAO = [re.compile(p) for p in _PADROES_INJECAO]


def detectar_injecao(texto: str) -> list[str]:
    t = normalizar(texto)
    return [m.group(0) for r in _RE_INJECAO if (m := r.search(t))]


def neutralizar_delimitadores(texto: str, tags: tuple[str, ...]) -> str:
    """Impede que o dado feche o delimitador (ex.: '</boletim>' dentro do boletim)."""
    for tag in tags:
        texto = re.sub(rf"(?i)<\s*/?\s*{tag}\s*>", f"[{tag}]", texto)
    return texto


_RE_LINK = re.compile(r"(?i)\b(https?://\S+|www\.\S+|\S+\.(com|net|org|xyz|ly|io|info|br)(/\S*)?)\b")


def encontrar_links(texto: str) -> list[str]:
    return [m.group(0) for m in _RE_LINK.finditer(texto)]
