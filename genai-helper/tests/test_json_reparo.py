"""Saídas estruturadas: extração de JSON, reparo e resposta segura."""
from app.llm_client import LLMTransientError
from app.mock_responder import RoteiroMock
from app.services.chat import RESPOSTA_SEGURA, ChatService
from app.structured import extrair_json
from tests.helpers import CHAT_OK, cliente_mock, j


def test_extrai_json_puro():
    assert extrair_json('{"a": 1}') == {"a": 1}


def test_extrai_json_com_cerca_markdown():
    assert extrair_json('Claro! Aqui está:\n```json\n{"a": 1}\n```\nEspero ter ajudado.') == {"a": 1}


def test_extrai_json_com_texto_extra():
    assert extrair_json('Resposta: {"a": {"b": [1, 2]}} fim') == {"a": {"b": [1, 2]}}


def test_texto_sem_json_retorna_none():
    assert extrair_json("Desculpe, não posso ajudar com isso.") is None
    assert extrair_json('{"a": 1,,}') is None
    assert extrair_json("") is None


def _svc(itens):
    roteiro = RoteiroMock(itens)
    return ChatService(cliente_mock(roteiro)), roteiro


def test_texto_puro_dispara_reparo_e_recupera():
    svc, roteiro = _svc(["Para se cadastrar abra o app.", j(CHAT_OK)])
    r = svc.responder("como me cadastro?")
    assert r.meta.reparo_json is True and r.meta.resposta_segura is False
    assert r.resposta == CHAT_OK["resposta"]
    assert [c["task"] for c in roteiro.chamadas] == ["chat", "chat:reparo"]
    # o prompt de reparo leva o erro de validação ao modelo
    assert "não contém um objeto JSON" in roteiro.chamadas[1]["messages"][-1]["content"]


def test_enum_invalido_reparo_envia_campo_com_erro():
    svc, roteiro = _svc([j({**CHAT_OK, "confianca": "certeza"}), j(CHAT_OK)])
    r = svc.responder("como me cadastro?")
    assert r.meta.reparo_json and r.confianca == "alta"
    assert "confianca" in roteiro.chamadas[1]["messages"][-1]["content"]


def test_json_quebrado_duas_vezes_gera_resposta_segura():
    svc, roteiro = _svc(['{"resposta": "oi", "confianca": ', "ainda não é json"])
    r = svc.responder("como me cadastro?")
    assert r.resposta == RESPOSTA_SEGURA
    assert r.meta.resposta_segura is True and r.precisa_atendimento_humano is True
    assert r.confianca == "baixa" and len(roteiro.chamadas) == 2  # só UMA chamada de reparo


def test_campo_faltando_e_reparo_falha_gera_resposta_segura():
    incompleto = {k: v for k, v in CHAT_OK.items() if k != "emergencia_detectada"}
    svc, _ = _svc([j(incompleto), j(incompleto)])
    assert svc.responder("como me cadastro?").meta.resposta_segura


def test_resposta_vazia_e_recusa_viram_resposta_segura():
    # resposta vazia conta como erro transitório (esgota os 2 modelos); depois vem a resposta segura
    svc, roteiro = _svc(["", "", "", ""])
    r = svc.responder("como me cadastro?")
    assert r.meta.resposta_segura and r.resposta == RESPOSTA_SEGURA
    # recusa em texto puro não passa na validação nem no reparo
    svc, _ = _svc(["Não posso ajudar com isso.", "Não posso."])
    assert svc.responder("como me cadastro?").meta.resposta_segura


def test_timeout_em_tudo_gera_resposta_segura():
    svc, _ = _svc([LLMTransientError("timeout")] * 10)
    r = svc.responder("como me cadastro?")
    assert r.meta.resposta_segura and r.meta.tentativas == 4  # 2 modelos x (1 + 1 retry)
