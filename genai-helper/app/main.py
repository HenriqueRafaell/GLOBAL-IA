"""API REST do genai-helper.

Rodar:  uvicorn app.main:app --reload   (dentro da pasta genai-helper/)
Docs interativas: http://localhost:8000/docs
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .config import BASE_DIR, Settings, get_settings
from .llm_client import LLMClient
from .logs import configurar_nivel, log_evento
from .retrieval import BaseConhecimento
from .schemas import Alerta, AprovarRequest, BoletimRequest, ChatRequest, ChatResponse, RejeitarRequest
from .services.boletins import BoletimService, ErroFluxo
from .services.chat import ChatService


def create_app(settings: Optional[Settings] = None, client: Optional[LLMClient] = None) -> FastAPI:
    settings = settings or get_settings()
    configurar_nivel(settings.log_level)
    client = client or LLMClient(settings)
    chat = ChatService(client, BaseConhecimento())
    boletins = BoletimService(client)

    app = FastAPI(
        title="genai-helper",
        version="1.0.0",
        description="Componente de IA Generativa do MVP CitizenTech: assistente do app e estruturador de boletins.",
    )
    app.state.settings, app.state.client, app.state.chat, app.state.boletins = settings, client, chat, boletins

    # A página web/index.html pode ser aberta direto do disco (origin "null") durante a demo.
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])

    @app.exception_handler(ErroFluxo)
    async def _erro_fluxo(_: Request, e: ErroFluxo):
        return JSONResponse(status_code=e.http_status, content={"detail": e.mensagem})

    def exigir_operador(x_operador_token: Optional[str] = Header(default=None)):
        if settings.operador_token and x_operador_token != settings.operador_token:
            raise HTTPException(status_code=401, detail="token de operador inválido ou ausente")

    # ------------------------------------------------------------------ #
    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "llm_mode": settings.llm_mode,
            "modelo": settings.llm_model,
            "fallbacks": settings.llm_fallback_models,
            "chave_configurada": bool(settings.openrouter_api_key),
        }

    @app.get("/", include_in_schema=False)
    def pagina_chat():
        return FileResponse(BASE_DIR / "web" / "index.html")

    # ---- Funcionalidade A ------------------------------------------- #
    @app.post("/chat", response_model=ChatResponse)
    def chat_endpoint(req: ChatRequest):
        return chat.responder(req.mensagem)

    # ---- Funcionalidade B ------------------------------------------- #
    @app.post("/boletins/estruturar", response_model=Alerta, status_code=201)
    def estruturar(req: BoletimRequest):
        """Chamado pelo robô UiPath. Devolve SEMPRE um rascunho aguardando aprovação."""
        return boletins.estruturar(req.texto)

    @app.get("/alertas", response_model=list[Alerta])
    def listar_alertas(status: Optional[str] = None):
        return boletins.repo.listar(status)

    @app.get("/alertas/liberados", response_model=list[Alerta])
    def alertas_liberados():
        """Fila do robô: somente alertas aprovados por um operador."""
        return boletins.liberados()

    @app.get("/alertas/{id_}", response_model=Alerta)
    def obter_alerta(id_: str):
        a = boletins.repo.obter(id_)
        if a is None:
            raise HTTPException(404, "alerta não encontrado")
        return a

    @app.post("/alertas/{id_}/aprovar", response_model=Alerta, dependencies=[Depends(exigir_operador)])
    def aprovar(id_: str, req: AprovarRequest):
        return boletins.aprovar(id_, req)

    @app.post("/alertas/{id_}/rejeitar", response_model=Alerta, dependencies=[Depends(exigir_operador)])
    def rejeitar(id_: str, req: RejeitarRequest):
        return boletins.rejeitar(id_, req)

    @app.post("/alertas/{id_}/disparado", response_model=Alerta)
    def disparado(id_: str):
        """O robô confirma o disparo; só funciona para alertas aprovados."""
        return boletins.marcar_disparado(id_)

    log_evento("app_iniciada", llm_mode=settings.llm_mode, modelo=settings.llm_model)
    return app


app = create_app()
