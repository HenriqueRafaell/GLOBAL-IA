import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.llm_client import LLMClient  # noqa: E402
from app.mock_responder import RoteiroMock  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def settings_mock(**kw) -> Settings:
    base = dict(
        llm_mode="mock", llm_model="principal/modelo", llm_fallback_models=["fallback/modelo:free"],
        llm_max_retries=1, llm_backoff_base_s=0.0, openrouter_api_key="",
    )
    base.update(kw)
    return Settings(**base)


@pytest.fixture
def roteiro():
    return RoteiroMock()


def cliente_mock(roteiro: RoteiroMock | None = None, **kw) -> LLMClient:
    return LLMClient(settings_mock(**kw), mock_responder=roteiro, sleep=lambda s: None)


def fixture(nome: str) -> str:
    return (FIXTURES / nome).read_text(encoding="utf-8")
