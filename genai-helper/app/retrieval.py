"""Base de conhecimento + recuperação de trechos por TF-IDF (scikit-learn).

- Cada arquivo .md de knowledge/ é dividido por seções "## ".
- Cada trecho recebe um id estável: "<arquivo>.md#<slug-da-secao>".
- A similaridade combina TF-IDF de palavras (com stopwords PT) e de n-gramas de
  caracteres (lida melhor com variações: cadastro/cadastrar/descadastrar).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .config import BASE_DIR
from .guardrails import normalizar

KNOWLEDGE_DIR = BASE_DIR / "knowledge"

STOPWORDS_PT = sorted({
    "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das", "em", "no", "na",
    "nos", "nas", "por", "pelo", "pela", "para", "pra", "com", "sem", "e", "ou", "que", "se", "eu", "voce",
    "ele", "ela", "meu", "minha", "seu", "sua", "isso", "esse", "essa", "este", "esta", "ao", "aos", "mais",
    "como", "qual", "quais", "quando", "onde", "porque", "por que", "ja", "nao", "sim", "ser", "ter", "tem",
    "e", "foi", "sao", "muito", "tambem", "so", "ate", "me", "te", "lhe", "nao", "the", "oi", "ola", "bom",
    "dia", "tarde", "noite", "quem", "fazer", "faz", "fiz", "obrigado", "obrigada", "favor", "gostaria", "quero", "queria", "preciso",
})


def slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalizar(texto)).strip("-")


@dataclass(frozen=True)
class Trecho:
    id: str
    arquivo: str
    titulo: str
    texto: str


def carregar_trechos(pasta: Path = KNOWLEDGE_DIR) -> list[Trecho]:
    trechos: list[Trecho] = []
    for arq in sorted(pasta.glob("*.md")):
        conteudo = arq.read_text(encoding="utf-8")
        titulo_doc = ""
        secao, linhas = None, []

        def fechar():
            if secao and "".join(linhas).strip():
                trechos.append(Trecho(
                    id=f"{arq.name}#{slug(secao)}", arquivo=arq.name,
                    titulo=f"{titulo_doc} - {secao}".strip(" -"), texto="\n".join(linhas).strip(),
                ))

        for linha in conteudo.splitlines():
            if linha.startswith("# ") and not titulo_doc:
                titulo_doc = linha[2:].strip()
            elif linha.startswith("## "):
                fechar()
                secao, linhas = linha[3:].strip(), []
            else:
                linhas.append(linha)
        fechar()
    return trechos


class BaseConhecimento:
    def __init__(self, trechos: list[Trecho] | None = None, limiar: float = 0.06):
        self.trechos = trechos if trechos is not None else carregar_trechos()
        self.limiar = limiar
        docs = [normalizar(f"{t.titulo}. {t.titulo}. {t.texto}") for t in self.trechos]
        self._vw = TfidfVectorizer(stop_words=STOPWORDS_PT, ngram_range=(1, 2), sublinear_tf=True)
        self._vc = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
        self._mw = self._vw.fit_transform(docs)
        self._mc = self._vc.fit_transform(docs)

    def buscar(self, pergunta: str, k: int = 3) -> list[tuple[Trecho, float]]:
        q = normalizar(pergunta)
        sw = cosine_similarity(self._vw.transform([q]), self._mw)[0]
        sc = cosine_similarity(self._vc.transform([q]), self._mc)[0]
        scores = 0.6 * sw + 0.4 * sc
        ordem = scores.argsort()[::-1][:k]
        # exige ao menos uma palavra (não-stopword) em comum: corta o ruído dos n-gramas
        # de caracteres em perguntas fora do escopo ("bolo", "jogo", "dólar")
        return [
            (self.trechos[i], float(scores[i]))
            for i in ordem
            if scores[i] >= self.limiar and sw[i] > 0
        ]

    def ids(self) -> set[str]:
        return {t.id for t in self.trechos}


def formatar_contexto(resultados: list[tuple[Trecho, float]]) -> str:
    if not resultados:
        return "<contexto>\n(nenhum trecho relevante foi encontrado na base de conhecimento)\n</contexto>"
    blocos = [f'<trecho id="{t.id}" titulo="{t.titulo}">\n{t.texto}\n</trecho>' for t, _ in resultados]
    return "<contexto>\n" + "\n\n".join(blocos) + "\n</contexto>"
