import pytest
from pydantic import ValidationError

from app.schemas import Alerta, BoletimLLMOutput, ChatLLMOutput, EdicaoAlerta, Meta
from tests.helpers import BOLETIM_OK, CHAT_OK


def test_chat_valido():
    out = ChatLLMOutput.model_validate(CHAT_OK)
    assert out.confianca == "alta" and out.fontes == ["como_usar.md#cadastro"]


def test_chat_aceita_media_com_acento():
    assert ChatLLMOutput.model_validate({**CHAT_OK, "confianca": "Média"}).confianca == "media"


@pytest.mark.parametrize("campo,valor", [("confianca", "altissima"), ("resposta", "   "), ("emergencia_detectada", "talvez")])
def test_chat_invalido(campo, valor):
    with pytest.raises(ValidationError):
        ChatLLMOutput.model_validate({**CHAT_OK, campo: valor})


def test_chat_campo_faltando():
    dados = dict(CHAT_OK)
    del dados["precisa_atendimento_humano"]
    with pytest.raises(ValidationError):
        ChatLLMOutput.model_validate(dados)


def test_boletim_valido_e_status_do_modelo_ignorado():
    out = BoletimLLMOutput.model_validate({**BOLETIM_OK, "status": "aprovado"})
    assert out.tipo_evento == "enchente"
    assert "status" not in out.model_dump()  # o modelo não controla o status


@pytest.mark.parametrize("campo,valor", [("tipo_evento", "furacao"), ("severidade", "media"), ("fonte", "Twitter")])
def test_boletim_enum_invalido(campo, valor):
    with pytest.raises(ValidationError):
        BoletimLLMOutput.model_validate({**BOLETIM_OK, campo: valor})


def test_alerta_final_rejeita_sms_maior_que_160():
    dados = dict(BOLETIM_OK)
    dados.update(id="x", criado_em="2026-11-19T00:00:00Z", meta=Meta(), mensagem_sms="a" * 161)
    with pytest.raises(ValidationError):
        Alerta.model_validate(dados)


def test_edicao_do_operador_valida_limite_e_campos():
    with pytest.raises(ValidationError):
        EdicaoAlerta(mensagem_sms="b" * 161)
    with pytest.raises(ValidationError):
        EdicaoAlerta.model_validate({"status": "aprovado"})  # campo não editável
