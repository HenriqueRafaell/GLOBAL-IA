"""Schemas Pydantic v2.

Dois níveis:
- *LLMOutput: o que exigimos do modelo (validação da saída estruturada).
- Modelos de API: o que o serviço devolve, já pós-processado e com metadados.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

Confianca = Literal["alta", "media", "baixa"]
TipoEvento = Literal["enchente", "alagamento", "deslizamento", "onda_de_calor", "tempestade", "outro"]
Severidade = Literal["baixa", "moderada", "alta", "extrema"]
Fonte = Literal["INMET", "Defesa Civil", "Cemaden", "outra"]
StatusAlerta = Literal["rascunho_aguardando_aprovacao", "aprovado", "rejeitado", "disparado"]

SMS_LIMITE = 160
WHATSAPP_LIMITE = 500


def _normalizar_confianca(v):
    """Aceita 'média' (com acento) como 'media' — variação comum e inofensiva."""
    if isinstance(v, str):
        v = v.strip().lower().replace("é", "e")
    return v


# --------------------------------------------------------------------------- #
# Metadados comuns
# --------------------------------------------------------------------------- #
class Meta(BaseModel):
    modelo_usado: Optional[str] = None
    tentativas: int = 0
    latencia_ms: int = 0
    fallback: bool = False
    reparo_json: bool = False
    resposta_segura: bool = False  # True quando caímos na resposta padrão por falha
    prompt_versao: Optional[str] = None


# --------------------------------------------------------------------------- #
# Funcionalidade A: chat
# --------------------------------------------------------------------------- #
class ChatLLMOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resposta: str = Field(min_length=1)
    confianca: Confianca
    fontes: list[str] = Field(default_factory=list)
    precisa_atendimento_humano: bool
    emergencia_detectada: bool

    @field_validator("confianca", mode="before")
    @classmethod
    def normalizar_confianca(cls, v):
        return _normalizar_confianca(v)

    @field_validator("resposta")
    @classmethod
    def resposta_nao_vazia(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("resposta vazia")
        return v.strip()


class ChatRequest(BaseModel):
    mensagem: str = Field(min_length=1, max_length=1000)


class ChatResponse(ChatLLMOutput):
    aviso: str = "Você está falando com um assistente automático. Ele pode errar."
    meta: Meta


# --------------------------------------------------------------------------- #
# Funcionalidade B: boletins
# --------------------------------------------------------------------------- #
class Regiao(BaseModel):
    model_config = ConfigDict(extra="ignore")

    municipio: str = Field(min_length=1)
    bairros: list[str] = Field(default_factory=list)


class BoletimLLMOutput(BaseModel):
    """Saída exigida do LLM. Limites de tamanho das mensagens NÃO ficam aqui:
    são tratados no pós-processamento (encurtar/truncar), para não descartar
    uma extração boa só porque o SMS ficou grande."""

    model_config = ConfigDict(extra="ignore")  # um "status" vindo do modelo é ignorado

    tipo_evento: TipoEvento
    severidade: Severidade
    regioes_afetadas: list[Regiao] = Field(default_factory=list)
    inicio: Optional[str] = None
    fim: Optional[str] = None
    fonte: Fonte
    recomendacoes: list[str] = Field(default_factory=list)
    mensagem_sms: str = Field(min_length=1)
    mensagem_whatsapp: str = Field(min_length=1)
    confianca: Confianca

    @field_validator("confianca", mode="before")
    @classmethod
    def normalizar_confianca(cls, v):
        return _normalizar_confianca(v)


class SmsCurtoLLMOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    mensagem_sms: str = Field(min_length=1)


class BoletimRequest(BaseModel):
    texto: str = Field(min_length=20, max_length=20000)
    origem: Optional[str] = Field(default=None, description="Identificador do robô/boletim (opcional)")


class Aprovacao(BaseModel):
    operador: str
    em: datetime
    acao: Literal["aprovado", "rejeitado"]
    campos_editados: list[str] = Field(default_factory=list)
    motivo: Optional[str] = None


class Alerta(BaseModel):
    id: str
    criado_em: datetime
    tipo_evento: TipoEvento
    severidade: Severidade
    regioes_afetadas: list[Regiao]
    inicio: Optional[str] = None
    fim: Optional[str] = None
    fonte: Fonte
    recomendacoes: list[str]
    mensagem_sms: str = Field(max_length=SMS_LIMITE)
    mensagem_whatsapp: str = Field(max_length=WHATSAPP_LIMITE)
    confianca: Confianca
    status: StatusAlerta = "rascunho_aguardando_aprovacao"
    requer_revisao_manual: bool = False
    motivos_revisao: list[str] = Field(default_factory=list)
    aprovacao: Optional[Aprovacao] = None
    disparado_em: Optional[datetime] = None
    meta: Meta


class EdicaoAlerta(BaseModel):
    """Campos que o operador pode corrigir antes de aprovar."""

    model_config = ConfigDict(extra="forbid")

    tipo_evento: Optional[TipoEvento] = None
    severidade: Optional[Severidade] = None
    regioes_afetadas: Optional[list[Regiao]] = None
    inicio: Optional[str] = None
    fim: Optional[str] = None
    recomendacoes: Optional[list[str]] = None
    mensagem_sms: Optional[str] = Field(default=None, min_length=1, max_length=SMS_LIMITE)
    mensagem_whatsapp: Optional[str] = Field(default=None, min_length=1, max_length=WHATSAPP_LIMITE)


class AprovarRequest(BaseModel):
    operador: str = Field(min_length=2, max_length=80)
    edicoes: Optional[EdicaoAlerta] = None
    confirmo_revisao_manual: bool = Field(
        default=False,
        description="Obrigatório quando o alerta tem requer_revisao_manual=true",
    )


class RejeitarRequest(BaseModel):
    operador: str = Field(min_length=2, max_length=80)
    motivo: str = Field(min_length=3, max_length=500)
