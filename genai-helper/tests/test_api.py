"""Testes de ponta a ponta da API FastAPI (modo mock)."""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.helpers import fixture, settings_mock


@pytest.fixture
def api():
    return TestClient(create_app(settings_mock()))


def test_health(api):
    r = api.get("/health").json()
    assert r["status"] == "ok" and r["llm_mode"] == "mock" and r["chave_configurada"] is False


def test_pagina_de_chat_e_servida(api):
    r = api.get("/")
    assert r.status_code == 200 and "aria-live" in r.text


def test_chat_endpoint(api):
    r = api.post("/chat", json={"mensagem": "como faço para trocar meu endereço?"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"resposta", "confianca", "fontes", "precisa_atendimento_humano", "emergencia_detectada", "meta"}
    assert set(body["meta"]) >= {"modelo_usado", "tentativas", "latencia_ms", "fallback"}


def test_chat_emergencia(api):
    body = api.post("/chat", json={"mensagem": "a água está entrando em casa"}).json()
    assert body["emergencia_detectada"] is True and body["resposta"].startswith("EMERGÊNCIA")


def test_chat_valida_entrada(api):
    assert api.post("/chat", json={"mensagem": ""}).status_code == 422
    assert api.post("/chat", json={"mensagem": "x" * 1001}).status_code == 422


def test_fluxo_completo_rpa(api):
    r = api.post("/boletins/estruturar", json={"texto": fixture("inmet_onda_calor.txt")})
    assert r.status_code == 201
    alerta = r.json()
    assert alerta["status"] == "rascunho_aguardando_aprovacao"
    assert api.get("/alertas/liberados").json() == []
    assert api.post(f"/alertas/{alerta['id']}/disparado").status_code == 409

    edicao = {"mensagem_sms": "x" * 161}
    assert api.post(f"/alertas/{alerta['id']}/aprovar", json={"operador": "op.ana", "edicoes": edicao}).status_code == 422

    r = api.post(f"/alertas/{alerta['id']}/aprovar", json={"operador": "op.ana", "confirmo_revisao_manual": True})
    assert r.status_code == 200 and r.json()["status"] == "aprovado"
    assert [a["id"] for a in api.get("/alertas/liberados").json()] == [alerta["id"]]
    assert api.post(f"/alertas/{alerta['id']}/disparado").json()["status"] == "disparado"
    assert api.get("/alertas/liberados").json() == []


def test_alerta_inexistente(api):
    assert api.get("/alertas/nao-existe").status_code == 404
    assert api.post("/alertas/nao-existe/aprovar", json={"operador": "op.ana"}).status_code == 404


def test_token_de_operador():
    api = TestClient(create_app(settings_mock(operador_token="segredo")))
    a = api.post("/boletins/estruturar", json={"texto": fixture("inmet_onda_calor.txt")}).json()
    corpo = {"operador": "op.ana", "confirmo_revisao_manual": True}
    assert api.post(f"/alertas/{a['id']}/aprovar", json=corpo).status_code == 401
    r = api.post(f"/alertas/{a['id']}/aprovar", json=corpo, headers={"X-Operador-Token": "segredo"})
    assert r.status_code == 200
