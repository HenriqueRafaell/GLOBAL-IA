"""Gera evidências de execução em docs/evidencias/.

Uso (de dentro de genai-helper/):
    python scripts/gerar_evidencias.py           # casos reais contra o OpenRouter (precisa de OPENROUTER_API_KEY no .env)
    python scripts/gerar_evidencias.py --mock    # mesmos casos com o LLM simulado (sem chave)

Salva, para cada caso: entrada, prompts enviados (já com dados pessoais mascarados),
resposta bruta do modelo e saída JSON validada. Também gera RESUMO.md e testes.txt
(saída do `pytest -v`).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.config import Settings  # noqa: E402
from app.llm_client import LLMClient  # noqa: E402
from app.services.boletins import BoletimService  # noqa: E402
from app.services.chat import ChatService  # noqa: E402

SAIDA = RAIZ / "docs" / "evidencias"
FIXTURES = RAIZ / "tests" / "fixtures"

CASOS_CHAT = [
    ("chat_01_cadastro", "Como faço pra me cadastrar no app?"),
    ("chat_02_foto_ilegivel", "Mandei a foto da conta de luz e o app disse que está ilegível. O que eu faço?"),
    ("chat_03_nao_recebi_com_dados_pessoais",
     "Não recebi o alerta da chuva de ontem. Meu número é (11) 98765-4321 e moro na Rua das Flores, 123."),
    ("chat_04_fora_de_escopo", "Qual vai ser o resultado do jogo do Corinthians no domingo?"),
    ("chat_05_emergencia", "Socorro, a água está entrando em casa e minha mãe é idosa"),
]
CASOS_BOLETIM = [
    ("boletim_01_enchente_defesa_civil", "defesa_civil_enchente.txt"),
    ("boletim_02_onda_de_calor_inmet", "inmet_onda_calor.txt"),
    ("boletim_03_tentativa_de_injecao", "boletim_com_injecao.txt"),
]


def _chamadas(client: LLMClient) -> list[dict]:
    return [
        {"task": c.task, "modelo": c.modelo, "messages": c.messages, "resposta_bruta": c.resposta, "erro": c.erro}
        for c in client.historico
    ]


def _salvar(nome: str, dados: dict) -> None:
    (SAIDA / f"{nome}.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _json_md(obj: dict) -> str:
    return "```json\n" + json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n```"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="usa o LLM simulado (não precisa de chave)")
    ap.add_argument("--sem-pytest", action="store_true", help="não roda o pytest")
    args = ap.parse_args()

    settings = Settings.from_env()
    if args.mock:
        settings.llm_mode = "mock"
    if settings.llm_mode != "mock" and not settings.openrouter_api_key:
        print("ERRO: OPENROUTER_API_KEY não configurada em genai-helper/.env.")
        print("Copie .env.example para .env, coloque a chave e rode de novo (ou use --mock).")
        return 2

    SAIDA.mkdir(parents=True, exist_ok=True)
    client = LLMClient(settings)
    chat = ChatService(client)
    boletins = BoletimService(client)
    modo = "MOCK (LLM simulado, sem chamada real)" if settings.llm_mode == "mock" else "OpenRouter (chamadas reais)"
    agora = datetime.now().strftime("%Y-%m-%d %H:%M")
    resumo = [
        "# Evidências de execução — genai-helper", "",
        f"- Gerado em: {agora}",
        f"- Modo: **{modo}**",
        f"- Modelo principal: `{settings.llm_model}` | fallbacks: `{', '.join(settings.llm_fallback_models)}`",
        f"- Temperatura: {settings.llm_temperature} | max_tokens: {settings.llm_max_tokens} | timeout: {settings.llm_timeout_s}s | retries: {settings.llm_max_retries}",
        "", "Cada caso tem um arquivo `.json` nesta pasta com a entrada, os prompts enviados (já mascarados), "
        "a resposta bruta do modelo e a saída validada.", "",
        "## Funcionalidade A — Assistente do app", "",
        "| Caso | Confiança | Fontes | Humano? | Emergência? | Modelo | Tentativas | Latência (ms) | Fallback | Reparo |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    detalhes: list[str] = []

    for nome, pergunta in CASOS_CHAT:
        client.historico.clear()
        r = chat.responder(pergunta)
        out = r.model_dump()
        _salvar(nome, {"caso": nome, "modo": modo, "gerado_em": agora, "entrada": {"mensagem": pergunta},
                       "chamadas_llm": _chamadas(client), "saida": out})
        m = r.meta
        resumo.append(
            f"| `{nome}` | {r.confianca} | {', '.join(r.fontes) or '-'} | {r.precisa_atendimento_humano} | "
            f"{r.emergencia_detectada} | `{m.modelo_usado}` | {m.tentativas} | {m.latencia_ms} | {m.fallback} | {m.reparo_json} |"
        )
        enviado = client.historico[0].messages[-1]["content"] if client.historico else "(nenhuma chamada)"
        detalhes += [f"### {nome}", "", f"**Pergunta:** {pergunta}", "",
                     "<details><summary>Mensagem enviada ao LLM (dados pessoais mascarados)</summary>", "",
                     "```text", enviado, "```", "</details>", "", "**Saída:**", "", _json_md(out), ""]
        print(f"[ok] {nome}: confianca={r.confianca} emergencia={r.emergencia_detectada} modelo={m.modelo_usado}")

    resumo += ["", "## Funcionalidade B — Estruturador de boletins", "",
               "| Caso | Tipo | Severidade | Regiões | SMS (chars) | Confiança | Status | Revisão manual | Motivos |",
               "|---|---|---|---|---|---|---|---|---|"]
    for nome, arq in CASOS_BOLETIM:
        texto = (FIXTURES / arq).read_text(encoding="utf-8")
        client.historico.clear()
        a = boletins.estruturar(texto)
        out = a.model_dump(mode="json")
        _salvar(nome, {"caso": nome, "modo": modo, "gerado_em": agora, "entrada": {"arquivo": f"tests/fixtures/{arq}", "texto": texto},
                       "chamadas_llm": _chamadas(client), "saida": out})
        regioes = "; ".join(f"{x.municipio} ({', '.join(x.bairros) or '-'})" for x in a.regioes_afetadas) or "-"
        resumo.append(
            f"| `{nome}` | {a.tipo_evento} | {a.severidade} | {regioes} | {len(a.mensagem_sms)} | {a.confianca} | "
            f"{a.status} | {a.requer_revisao_manual} | {', '.join(a.motivos_revisao) or '-'} |"
        )
        detalhes += [f"### {nome}", "", f"**Entrada:** `tests/fixtures/{arq}`", "", "```text", texto.strip(), "```", "",
                     "**Saída (rascunho aguardando aprovação):**", "", _json_md(out), ""]
        print(f"[ok] {nome}: tipo={a.tipo_evento} sev={a.severidade} revisao={a.requer_revisao_manual}")

    # demonstração da pessoa no circuito: aprova o 1º boletim e mostra a fila do robô
    from app.schemas import AprovarRequest
    from app.services.boletins import ErroFluxo

    resumo += ["", "## Pessoa no circuito", "",
               f"- Antes da aprovação, `/alertas/liberados` tinha {len(boletins.liberados())} alerta(s): "
               "todos nascem como `rascunho_aguardando_aprovacao`."]
    candidato = next((x for x in boletins.repo.listar() if x.regioes_afetadas and "possivel_tentativa_de_injecao_no_boletim" not in x.motivos_revisao), None)
    if candidato:
        try:
            aprovado = boletins.aprovar(candidato.id, AprovarRequest(operador="operador.demo", confirmo_revisao_manual=True))
            resumo.append(f"- O operador `operador.demo` aprovou o alerta `{aprovado.id}`; agora a fila do robô contém: "
                          f"`{[x.id for x in boletins.liberados()]}`.")
        except ErroFluxo as e:
            resumo.append(f"- Tentativa de aprovação recusada pelo fluxo: {e.mensagem}")
    resumo.append("- O alerta com tentativa de injeção continua como rascunho e exige `confirmo_revisao_manual=true` "
                  "para ser aprovado.")

    resumo += ["", "## Detalhes dos casos", "", *detalhes]

    if not args.sem_pytest:
        p = subprocess.run([sys.executable, "-m", "pytest", "-v", "-p", "no:cacheprovider"], cwd=RAIZ,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        (SAIDA / "testes.txt").write_text(p.stdout + ("\n" + p.stderr if p.returncode else ""), encoding="utf-8")
        ultima = [l for l in p.stdout.strip().splitlines() if l.strip()][-1] if p.stdout.strip() else "(sem saída)"
        resumo[4:4] = [f"- Resultado do `pytest -v`: {ultima.strip('= ')} (ver `testes.txt`)"]
        print(f"[ok] pytest: {ultima}")

    (SAIDA / "RESUMO.md").write_text("\n".join(resumo) + "\n", encoding="utf-8")
    print(f"Evidências salvas em {SAIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
