"""Cliente OpenRouter: retries com backoff, fallback de modelo, headers e falhas HTTP.

Usa httpx.MockTransport: exercita o caminho HTTP real sem internet."""
import json

import httpx
import pytest

from app.llm_client import LLMClient, LLMTransientError, LLMUnavailable
from app.mock_responder import RoteiroMock
from tests.helpers import CHAT_OK, cliente_mock, settings_mock

MSGS = [{"role": "user", "content": "oi"}]


def _ok(conteudo: str = json.dumps(CHAT_OK)) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": conteudo}}]})


def _cliente_http(respostas, sleeps=None, **kw):
    """respostas: lista de httpx.Response ou exceções, consumidas em ordem."""
    pedidos = []
    fila = list(respostas)

    def handler(req: httpx.Request):
        pedidos.append(req)
        item = fila.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    kw.setdefault("llm_max_retries", 2)
    s = settings_mock(llm_mode="openrouter", openrouter_api_key="sk-teste", **kw)
    sleeps = sleeps if sleeps is not None else []
    c = LLMClient(s, transport=httpx.MockTransport(handler), sleep=sleeps.append)
    return c, pedidos


def test_sucesso_envia_modelo_headers_e_json_mode():
    c, pedidos = _cliente_http([_ok()])
    r = c.complete(MSGS, task="chat")
    assert r.modelo_usado == "principal/modelo" and r.tentativas == 1 and not r.fallback
    req = pedidos[0]
    corpo = json.loads(req.content)
    assert corpo["model"] == "principal/modelo"
    assert corpo["response_format"] == {"type": "json_object"}
    assert corpo["temperature"] == 0.2
    assert req.headers["Authorization"] == "Bearer sk-teste"
    assert "HTTP-Referer" in req.headers and "X-Title" in req.headers
    assert str(req.url).endswith("/chat/completions")


def test_429_faz_retry_com_backoff_exponencial():
    sleeps = []
    c, _ = _cliente_http([httpx.Response(429), httpx.Response(429), _ok()], sleeps=sleeps, llm_backoff_base_s=1.0)
    r = c.complete(MSGS)
    assert r.tentativas == 3 and r.modelo_usado == "principal/modelo"
    assert sleeps == [1.0, 2.0]  # 1 * 2**0, 1 * 2**1


def test_500_esgota_principal_e_usa_fallback():
    c, pedidos = _cliente_http([httpx.Response(500)] * 3 + [_ok()])
    r = c.complete(MSGS)
    assert r.fallback is True and r.modelo_usado == "fallback/modelo:free" and r.tentativas == 4
    assert json.loads(pedidos[-1].content)["model"] == "fallback/modelo:free"


def test_timeout_usa_fallback():
    c, _ = _cliente_http([httpx.ReadTimeout("lento")] * 3 + [_ok()])
    r = c.complete(MSGS)
    assert r.fallback and r.modelo_usado == "fallback/modelo:free"


def test_401_nao_repete_no_mesmo_modelo():
    c, _ = _cliente_http([httpx.Response(401), _ok()])
    r = c.complete(MSGS)
    assert r.fallback and r.tentativas == 2  # sem retry inútil em 4xx


def test_modelo_sem_suporte_a_response_format_tenta_sem():
    c, pedidos = _cliente_http([httpx.Response(400, text='{"error":"response_format not supported"}'), _ok()])
    r = c.complete(MSGS)
    assert not r.fallback
    assert "response_format" not in json.loads(pedidos[1].content)


def test_erro_dentro_de_200_e_resposta_vazia_sao_repetidos():
    c, _ = _cliente_http([
        httpx.Response(200, json={"error": {"code": 502, "message": "upstream"}}),
        _ok(""),
        _ok(),
    ])
    assert c.complete(MSGS).tentativas == 3


def test_tudo_falha_levanta_llm_unavailable():
    c, _ = _cliente_http([httpx.Response(503)] * 6)
    with pytest.raises(LLMUnavailable) as e:
        c.complete(MSGS)
    assert e.value.tentativas == 6


def test_sem_chave_nao_chama_api():
    s = settings_mock(llm_mode="openrouter", openrouter_api_key="")
    chamado = []
    c = LLMClient(s, transport=httpx.MockTransport(lambda r: chamado.append(r) or _ok()))
    with pytest.raises(LLMUnavailable, match="ausente"):
        c.complete(MSGS)
    assert chamado == []


def test_fallback_em_modo_mock():
    roteiro = RoteiroMock([LLMTransientError("timeout"), LLMTransientError("timeout"), json.dumps(CHAT_OK)])
    r = cliente_mock(roteiro).complete(MSGS, task="chat")
    assert r.fallback
    assert [c["model"] for c in roteiro.chamadas] == ["principal/modelo", "principal/modelo", "fallback/modelo:free"]
