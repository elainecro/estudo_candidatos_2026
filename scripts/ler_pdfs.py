#!/usr/bin/env python3
"""Lê os PDFs dos zips do TSE em data/cache/ e enche a ficha:

  --propostas   proposta_governo_2026_*.zip -> texto em data/propostas/<tse_id>.txt
                e o campo 'proposta_governo' (páginas, tamanho, arquivo). Só
                existe para presidente e governador: senador e deputado não
                entregam plano de governo ao TSE.
  --certidoes   certidao_criminal_2026_*.zip -> lê cada certidão, separa
                'nada consta' de 'consta', extrai números de processo (formato
                CNJ) e grava 'certidoes_resumo' + 'certidoes_flag' na ficha.

Precisa do pypdf (Python puro):  pip3 install pypdf
Uso:
    python3 scripts/ler_pdfs.py --propostas
    python3 scripts/ler_pdfs.py --certidoes         # ~3.800 PDFs no ES, leva uns minutos
    python3 scripts/build_bundle.py

Cuidado com a leitura das certidões: é uma heurística sobre o texto. Uma
certidão 'com apontamentos' pode listar processo já arquivado, ou em que a
pessoa não é ré. Serve para saber onde olhar, não para condenar.
"""
import argparse
import io
import json
import logging
import pathlib
import re
import sys
import zipfile

# O pypdf avisa "fontTools is required" em cada PDF sem fonte embutida; não afeta a extração.
logging.getLogger("pypdf").setLevel(logging.ERROR)

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
PROPOSTAS = ROOT / "data" / "propostas"
CAND = ROOT / "data" / "candidatos.json"

RE_SQ = re.compile(r"(\d{11,12})")
RE_CNJ = re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")
RE_LIMPA = re.compile(r"nada\s+consta|n[ãa]o\s+consta(m|ndo)?\b|inexist(e|em|ência)|n[ãa]o\s+h[áa]\s+(registro|distribui|processo|ação|feito)|sem\s+(registro|apontamento|ocorr)|certid[ãa]o\s+negativa|\bnegativa\b", re.I)
RE_POSITIVA = re.compile(r"certid[ãa]o\s+positiva|\bpositiva\b|constam?\s+(os\s+)?(seguintes|registro|processo|feito|a[çc][ãa]o)|em\s+tramita[çc][ãa]o|distribu[íi]d[oa]s?\s+(os\s+)?(seguintes|processos)", re.I)
ORGAOS = [
    (re.compile(r"supremo\s+tribunal\s+federal", re.I), "STF"),
    (re.compile(r"superior\s+tribunal\s+de\s+justi", re.I), "STJ"),
    (re.compile(r"tribunal\s+superior\s+eleitoral|justi[çc]a\s+eleitoral|tribunal\s+regional\s+eleitoral", re.I), "Justiça Eleitoral"),
    (re.compile(r"justi[çc]a\s+militar", re.I), "Justiça Militar"),
    (re.compile(r"tribunal\s+regional\s+federal|justi[çc]a\s+federal|se[çc][ãa]o\s+judici[áa]ria", re.I), "Justiça Federal"),
    (re.compile(r"tribunal\s+de\s+justi[çc]a|justi[çc]a\s+estadual|poder\s+judici[áa]rio\s+do\s+estado|comarca", re.I), "Justiça Estadual"),
]
RE_QUITACAO = re.compile(r"quita[çc][ãa]o\s+eleitoral", re.I)
RE_GRAU = re.compile(r"(1[ºo°]|primeiro)\s+grau|(2[ºo°]|segundo)\s+grau|segunda\s+inst[âa]ncia|primeira\s+inst[âa]ncia", re.I)


def texto_pdf(dados: bytes, max_paginas: int | None = None) -> tuple[str, int]:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise SystemExit("instale o pypdf:  pip3 install pypdf")
    try:
        r = PdfReader(io.BytesIO(dados))
        n = len(r.pages)
        partes = []
        for i, p in enumerate(r.pages):
            if max_paginas and i >= max_paginas:
                break
            try:
                partes.append(p.extract_text() or "")
            except Exception:  # noqa: BLE001
                partes.append("")
        return "\n".join(partes), n
    except Exception as exc:  # noqa: BLE001
        return "", 0


def classificar_certidao(texto: str) -> dict:
    """Devolve orgao, grau, tipo, status ('nada consta' | 'com apontamentos' | 'indeterminada'), processos."""
    t = re.sub(r"\s+", " ", texto or "")
    orgao = next((nome for rx, nome in ORGAOS if rx.search(t)), "não identificado")
    grau = None
    mg = RE_GRAU.search(t)
    if mg:
        grau = "2º grau" if re.search(r"2|segund", mg.group(0), re.I) else "1º grau"
    tipo = "quitação eleitoral" if RE_QUITACAO.search(t) and "crim" not in t.lower() else "criminal"
    processos = sorted(set(RE_CNJ.findall(t)))
    if not t.strip():
        status = "indeterminada"
        obs = "PDF sem texto (provavelmente imagem escaneada)"
    elif processos:
        status = "com apontamentos"
        obs = f"{len(processos)} processo(s) listado(s)"
    elif RE_POSITIVA.search(t) and not RE_LIMPA.search(t):
        status = "com apontamentos"
        obs = "texto indica certidão positiva, sem número de processo legível"
    elif RE_LIMPA.search(t):
        status = "nada consta"
        obs = None
    else:
        status = "indeterminada"
        obs = "não achei 'nada consta' nem processo; conferir o PDF"
    trecho = None
    if status == "com apontamentos":
        m = RE_CNJ.search(t) or RE_POSITIVA.search(t)
        if m:
            a = max(0, m.start() - 160)
            trecho = t[a:m.end() + 220]
    return {"orgao": orgao, "grau": grau, "tipo": tipo, "status": status, "processos": processos, "obs": obs, "trecho": trecho}


def carregar():
    return json.loads(CAND.read_text(encoding="utf-8"))


def salvar(doc):
    CAND.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ler_propostas(doc):
    por_sq = {str(c.get("tse_id")): c for c in doc["candidatos"] if c.get("tse_id")}
    PROPOSTAS.mkdir(parents=True, exist_ok=True)
    zips = sorted(CACHE.glob("proposta_governo_2026_*.zip"))
    if not zips:
        print("nenhum proposta_governo_2026_*.zip em data/cache/ (o do ES tem os governadores; o _BR tem os presidenciáveis)")
        return
    feitos = 0
    for zp in zips:
        with zipfile.ZipFile(zp) as z:
            for nome in z.namelist():
                if not nome.lower().endswith(".pdf"):
                    continue
                m = RE_SQ.search(nome)
                c = por_sq.get(m.group(1)) if m else None
                if not c:
                    print(f"  {nome}: sem candidato correspondente (tse_id)")
                    continue
                texto, paginas = texto_pdf(z.read(nome))
                texto = re.sub(r"[ \t]+", " ", texto)
                texto = re.sub(r"\n{3,}", "\n\n", texto).strip()
                arq = PROPOSTAS / f"{c['tse_id']}.txt"
                arq.write_text(texto, encoding="utf-8")
                c["proposta_governo"] = {"arquivo": f"data/propostas/{c['tse_id']}.txt", "paginas": paginas, "caracteres": len(texto),
                                         "pdf_original": nome, "fonte": "TSE DivulgaCand (proposta de governo anexada ao registro)",
                                         "legivel": len(texto) > 500}
                print(f"  {c['nome_urna']} ({c['cargo']}): {paginas} páginas, {len(texto):,} caracteres" + ("" if len(texto) > 500 else "  <- quase sem texto: PDF de imagem?"))
                feitos += 1
    print(f"{feitos} propostas extraídas para data/propostas/")


def ler_certidoes(doc):
    por_sq = {str(c.get("tse_id")): c for c in doc["candidatos"] if c.get("tse_id")}
    zips = sorted(CACHE.glob("certidao_criminal_2026_*.zip"))
    if not zips:
        print("nenhum certidao_criminal_2026_*.zip em data/cache/")
        return
    for c in por_sq.values():
        c["certidoes_resumo"] = []
    total = 0
    for zp in zips:
        with zipfile.ZipFile(zp) as z:
            nomes = [n for n in z.namelist() if n.lower().endswith(".pdf")]
            print(f"  {zp.name}: {len(nomes)} PDFs")
            for i, nome in enumerate(nomes, 1):
                m = RE_SQ.search(nome)
                c = por_sq.get(m.group(1)) if m else None
                if not c:
                    continue
                texto, paginas = texto_pdf(z.read(nome), max_paginas=4)
                item = classificar_certidao(texto)
                item["arquivo"] = f"data/cache/{zp.name}:{nome}"
                c["certidoes_resumo"].append(item)
                total += 1
                if i % 250 == 0:
                    print(f"    {i}/{len(nomes)}")
    limpas = apont = indet = 0
    for c in por_sq.values():
        r = c.get("certidoes_resumo") or []
        if not r:
            c.pop("certidoes_resumo", None)
            continue
        if any(x["status"] == "com apontamentos" for x in r):
            c["certidoes_flag"] = "com apontamentos"
            apont += 1
        elif all(x["status"] == "nada consta" or x["tipo"] == "quitação eleitoral" for x in r):
            c["certidoes_flag"] = "nada consta"
            limpas += 1
        else:
            c["certidoes_flag"] = "indeterminada"
            indet += 1
    print(f"{total} certidões lidas. Candidatos: {limpas} só 'nada consta', {apont} com apontamentos, {indet} com alguma certidão ilegível.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--propostas", action="store_true")
    ap.add_argument("--certidoes", action="store_true")
    a = ap.parse_args()
    if not (a.propostas or a.certidoes):
        ap.error("use --propostas e/ou --certidoes")
    doc = carregar()
    if a.propostas:
        print("== Propostas de governo")
        ler_propostas(doc)
    if a.certidoes:
        print("== Certidões criminais")
        ler_certidoes(doc)
    salvar(doc)
    print(f"gravado: {CAND.relative_to(ROOT)}. Agora rode: python3 scripts/build_bundle.py")


if __name__ == "__main__":
    main()
