"""Utilitários compartilhados pelos testes (todos rodam em LLM_MODE=mock, sem internet)."""
from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings
from app.llm_client import LLMClient
from app.mock_responder import RoteiroMock

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def settings_mock(**kw) -> Settings:
    base = dict(
        llm_mode="mock", llm_model="principal/modelo", llm_fallback_models=["fallback/modelo:free"],
        llm_max_retries=1, llm_backoff_base_s=0.0, openrouter_api_key="",
    )
    base.update(kw)
    return Settings(**base)


def cliente_mock(roteiro: RoteiroMock | None = None, **kw) -> LLMClient:
    return LLMClient(settings_mock(**kw), mock_responder=roteiro, sleep=lambda s: None)


def fixture(nome: str) -> str:
    return (FIXTURES / nome).read_text(encoding="utf-8")


def j(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


CHAT_OK = {
    "resposta": "Abra o app e toque em Cadastrar.", "confianca": "alta",
    "fontes": ["como_usar.md#cadastro"], "precisa_atendimento_humano": False, "emergencia_detectada": False,
}

BOLETIM_OK = {
    "tipo_evento": "enchente", "severidade": "alta",
    "regioes_afetadas": [{"municipio": "São Paulo", "bairros": ["Jardim Pantanal", "Vila Itaim"]}],
    "inicio": "2026-11-19 07:00", "fim": "2026-11-20 07:00", "fonte": "Defesa Civil",
    "recomendacoes": ["Procure local alto.", "Não atravesse rua alagada."],
    "mensagem_sms": "ALERTA enchente no Jd Pantanal e Vila Itaim ate 20/11 7h. Va para local alto. Emergencia: 199",
    "mensagem_whatsapp": "ALERTA DE ENCHENTE em São Paulo (Jardim Pantanal, Vila Itaim). Vá para local alto. "
                         "Em emergência ligue 199 (Defesa Civil) ou 193 (Bombeiros).",
    "confianca": "alta",
}
