#!/usr/bin/env python3
"""Produção legislativa de vereadores no portal "Câmara sem Papel" (Processo Legislativo Eletrônico).

A Câmara de Vitória usa esse sistema (camarasempapel.cmv.es.gov.br). Cada autor tem um id;
a produção fica em spl/consulta-producao.aspx?autor=ID, com botão de exportar CSV.

O que o script faz:
  1. lê spl/consulta-autor.aspx e monta a lista nome -> id de autor
  2. casa os candidatos que disputaram vereador no município (histórico do TSE) com esses nomes
  3. para cada um, baixa a produção (CSV via postback; se falhar, lê as páginas HTML)
  4. resume: total, por tipo, por situação, lista de projetos (lei, lei complementar, emenda à
     lei orgânica, resolução, decreto) e as proposições mais recentes
  5. grava em candidatos.json como 'camara_municipal'

Uso:
    python3 scripts/fetch_camara_municipal.py                 # Vitória
    python3 scripts/fetch_camara_municipal.py --candidato jocelino
    python3 scripts/fetch_camara_municipal.py --base https://camarasempapel.<outra>.es.gov.br --municipio "Vila Velha"
    DEBUG=1 ...                                               # imprime cada pedido e salva o HTML em data/cache/cmv/

Respeita o site: uma pausa de 1 s entre pedidos. Lê ano a ano, até 100 páginas de 100 por ano (--max-paginas).
Quem tem milhares de proposições por ano (votos de louvor, indicações) leva alguns minutos.
"""
import argparse
import csv
import html as htmlmod
import io
import json
import os
import pathlib
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _chaves  # noqa: E402,F401

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAND = ROOT / "data" / "candidatos.json"
CACHE = ROOT / "data" / "cache" / "cmv"
HOJE = time.strftime("%Y-%m-%d")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "pt-BR,pt;q=0.9"}
DEBUG = bool(os.environ.get("DEBUG"))
PAUSA = 1.0
MAX_PAGINAS = 100   # páginas de 100 por ano; --max-paginas muda

TIPOS_PROJETO = ("projeto de lei", "projeto de emenda", "projeto de resolução", "projeto de resolucao", "projeto de decreto", "p. de lei", "pl ")


# ------------------------------------------------------------------ http

def _req(url: str, dados: dict | None = None) -> bytes:
    corpo = urllib.parse.urlencode(dados).encode("utf-8") if dados is not None else None
    h = dict(UA)
    if corpo is not None:
        h["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=corpo, headers=h, method="POST" if corpo is not None else "GET")
    if DEBUG:
        print(f"  {'POST' if corpo else 'GET'} {url}" + (f" ({len(corpo)} bytes)" if corpo else ""), file=sys.stderr)
    with urllib.request.urlopen(req, timeout=90) as r:
        dados_resp = r.read()
        ctype = r.headers.get("Content-Type", "")
    time.sleep(PAUSA)
    return dados_resp, ctype


def decodificar(b: bytes) -> str:
    for enc in ("utf-8", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "replace")


def campos_ocultos(html: str) -> dict:
    """__VIEWSTATE, __VIEWSTATEGENERATOR, __EVENTVALIDATION e afins."""
    out = {}
    for m in re.finditer(r'<input[^>]+type="hidden"[^>]+name="([^"]+)"[^>]*value="([^"]*)"', html):
        out[m.group(1)] = htmlmod.unescape(m.group(2))
    for m in re.finditer(r'<input[^>]+name="([^"]+)"[^>]+type="hidden"[^>]*value="([^"]*)"', html):
        out.setdefault(m.group(1), htmlmod.unescape(m.group(2)))
    return out


# ------------------------------------------------------------------ parsers

def _normal(s: str) -> str:
    s = "".join(ch for ch in unicodedata.normalize("NFD", s or "") if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()


def listar_autores(html: str) -> dict[str, dict]:
    """'Professor Jocelino(8868)' + links consulta-producao.aspx?autor=391&ano=2025 -> {'professor jocelino': {'id': 391, 'anos': [2025, 2026]}}"""
    autores = {}
    cards = re.split(r"class=['\"]card-title collapsed['\"]", html)[1:]
    for card in cards:
        m = re.match(r"[^>]*>\s*([^<]+?)\s*\(\s*\d+\s*\)\s*<", card, re.S)
        if not m:
            continue
        nome = htmlmod.unescape(m.group(1)).strip()
        ids = re.findall(r"consulta-producao\.aspx\?autor=(\d+)", card)
        if not ids:
            continue
        anos = sorted({int(a) for a in re.findall(r"consulta-producao\.aspx\?autor=\d+&(?:amp;)?ano=(\d{4})", card)})
        autores[" ".join(_normal(nome))] = {"id": int(ids[0]), "anos": anos}
    return autores


def total_localizado(html: str) -> int | None:
    m = re.search(r"Localizada\(s\)\s*(?:<[^>]+>\s*)*([\d.]+)\s*(?:<[^>]+>\s*)*proposi", html)
    return int(m.group(1).replace(".", "")) if m else None


def itens_html(html: str, base: str) -> list[dict]:
    """Extrai os itens da listagem (kt-widget5__item)."""
    itens = []
    blocos = re.split(r'class="kt-widget5__item', html)[1:]
    for b in blocos:
        t = re.search(r'kt-widget5__title["\']?>\s*(.*?)\s*</a>', b, re.S)
        e = re.search(r'kt-widget5__desc["\']?>\s*(.*?)\s*</a>', b, re.S)
        pid = re.search(r"processo\.aspx\?id=(\d+)", b)
        def campo(rotulo):
            m = re.search(rotulo + r":?</span>\s*<(?:a|span)[^>]*>\s*(.*?)\s*</(?:a|span)>", b, re.S)
            return htmlmod.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else None
        titulo = htmlmod.unescape(re.sub(r"<[^>]+>", "", t.group(1))).strip() if t else ""
        tm = re.match(r"(.+?)\s+n[°ºo]\s*([\d./-]+)", titulo)
        itens.append({
            "tipo": (tm.group(1) if tm else titulo).strip(),
            "numero": tm.group(2) if tm else None,
            "ementa": htmlmod.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", e.group(1)))).strip() if e else None,
            "processo": campo("Processo N°"),
            "data": (campo("Data") or "")[:10] or None,
            "situacao": campo("Situação"),
            "atividade": campo("Atividade Atual"),
            "url": f"{base}/spl/processo.aspx?id={pid.group(1)}" if pid else None,
        })
    return itens


def itens_csv(texto: str, base: str) -> list[dict]:
    """CSV exportado pelo portal. Colunas variam; casa por palavra-chave no cabeçalho."""
    amostra = texto[:4000]
    delim = ";" if amostra.count(";") >= amostra.count(",") else ","
    rows = list(csv.DictReader(io.StringIO(texto), delimiter=delim))
    if not rows:
        return []
    cols = {k: k for k in rows[0].keys() if k}
    def acha(*chaves):
        for k in cols:
            kn = " ".join(_normal(k))
            if any(ch in kn for ch in chaves):
                return k
        return None
    c_tipo = acha("tipo", "especie")
    c_num = acha("numero", "n ")
    c_ementa = acha("ementa", "assunto", "descricao")
    c_data = acha("data")
    c_sit = acha("situacao")
    c_ativ = acha("atividade")
    c_id = acha("id")
    c_proc = acha("processo")
    itens = []
    for r in rows:
        tipo = (r.get(c_tipo) or "").strip() if c_tipo else ""
        titulo = tipo
        if not c_tipo and c_ementa:
            titulo = (r.get(c_ementa) or "").strip()
        pid = (r.get(c_id) or "").strip() if c_id else ""
        itens.append({
            "tipo": tipo or None,
            "numero": (r.get(c_num) or "").strip() if c_num else None,
            "ementa": re.sub(r"\s+", " ", (r.get(c_ementa) or "")).strip() if c_ementa else None,
            "processo": (r.get(c_proc) or "").strip() if c_proc else None,
            "data": ((r.get(c_data) or "").strip() or None)[:10] if c_data and r.get(c_data) else None,
            "situacao": (r.get(c_sit) or "").strip() if c_sit else None,
            "atividade": (r.get(c_ativ) or "").strip() if c_ativ else None,
            "url": f"{base}/spl/processo.aspx?id={pid}" if pid.isdigit() else None,
        })
    return itens


# ------------------------------------------------------------------ coleta

def baixar_producao(base: str, autor_id: int, ano: int | None = None) -> tuple[list[dict], int | None, str]:
    """Tenta o CSV; se vier HTML, pagina. Devolve (itens, total_declarado, modo)."""
    url = f"{base}/spl/consulta-producao.aspx?autor={autor_id}" + (f"&ano={ano}" if ano else "")
    raw, _ = _req(url)
    html = decodificar(raw)
    if DEBUG:
        CACHE.mkdir(parents=True, exist_ok=True)
        (CACHE / f"autor_{autor_id}_p1.html").write_text(html, encoding="utf-8")
    total = total_localizado(html)
    ocultos = campos_ocultos(html)
    # 1) exportação CSV
    if "__VIEWSTATE" in ocultos:
        form = dict(ocultos)
        form["ctl00$ContentPlaceHolder1$btn_export_csv"] = "CSV"
        form.setdefault("ctl00$ContentPlaceHolder1$ddl_ItensExibidos", "10")
        try:
            raw2, ctype = _req(url, form)
            texto = decodificar(raw2)
            if "text/html" not in ctype.lower() and not texto.lstrip().lower().startswith("<!doctype") and "<html" not in texto[:500].lower():
                itens = itens_csv(texto, base)
                if itens:
                    return itens, total, "csv"
            elif DEBUG:
                (CACHE / f"autor_{autor_id}_export.html").write_text(texto, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            print(f"  exportação CSV falhou ({exc}); lendo as páginas", file=sys.stderr)
    # 2) HTML paginado: pede 100 por página, depois "próxima" até acabar
    itens = itens_html(html, base)
    try:
        if "__VIEWSTATE" in ocultos and "ctl00$ContentPlaceHolder1$ddl_ItensExibidos" in html:
            form = dict(ocultos)
            form["__EVENTTARGET"] = "ctl00$ContentPlaceHolder1$ddl_ItensExibidos"
            form["__EVENTARGUMENT"] = ""
            form["ctl00$ContentPlaceHolder1$ddl_ItensExibidos"] = "100"
            raw2, _ = _req(url, form)
            html = decodificar(raw2)
            itens = itens_html(html, base)
            ocultos = campos_ocultos(html)
        pagina = 1
        vistos = {i.get("url") for i in itens}
        while "lbNext" in html and pagina < MAX_PAGINAS and "__VIEWSTATE" in ocultos:
            if pagina % 10 == 0:
                print(f"      página {pagina}, {len(itens)} lidas até agora", flush=True)
            form = dict(ocultos)
            form["__EVENTTARGET"] = "ctl00$ContentPlaceHolder1$lbNext"
            form["__EVENTARGUMENT"] = ""
            form["ctl00$ContentPlaceHolder1$ddl_ItensExibidos"] = "100"
            raw2, _ = _req(url, form)
            html = decodificar(raw2)
            novos = [i for i in itens_html(html, base) if i.get("url") not in vistos]
            if not novos:
                break
            itens.extend(novos)
            vistos.update(i.get("url") for i in novos)
            ocultos = campos_ocultos(html)
            pagina += 1
    except Exception as exc:  # noqa: BLE001
        print(f"  paginação interrompida ({exc})", file=sys.stderr)
    return itens, total, "html"


def resumir(itens: list[dict], total: int | None, base: str, autor_id: int, casa: str) -> dict:
    por_tipo, por_sit = {}, {}
    for i in itens:
        por_tipo[i.get("tipo") or "?"] = por_tipo.get(i.get("tipo") or "?", 0) + 1
        por_sit[i.get("situacao") or "?"] = por_sit.get(i.get("situacao") or "?", 0) + 1
    def data_ord(i):
        d = i.get("data") or ""
        m = re.match(r"(\d{2})/(\d{2})/(\d{4})", d)
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else d
    projetos = [i for i in itens if any(k in (i.get("tipo") or "").lower() for k in TIPOS_PROJETO)]
    outros = sorted([i for i in itens if i not in projetos], key=data_ord, reverse=True)[:12]
    # palavras mais frequentes nas ementas das indicações (dá o "tema" do vereador)
    parar = set("de da do das dos e a o as os em no na nos nas para por com que ao aos à às um uma sr sra exma exmo prefeita prefeito municipal vitoria vitória es indico requeiro requerimento informacao secretaria competente meio realize seja sejam senhor senhora cristhine samorini pazolini lorenzo acerca sobre toda todo todas todos junto providencias necessarias adotadas".split())
    freq = {}
    for i in itens:
        for w in _normal(i.get("ementa") or ""):
            if len(w) > 3 and w not in parar:
                freq[w] = freq.get(w, 0) + 1
    temas = [w for w, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:12]]
    return {
        "casa": casa, "autor_id": autor_id, "url": f"{base}/spl/consulta-producao.aspx?autor={autor_id}",
        "total_declarado": total, "total_lido": len(itens), "consultado_em": HOJE,
        "por_tipo": dict(sorted(por_tipo.items(), key=lambda kv: -kv[1])),
        "por_situacao": dict(sorted(por_sit.items(), key=lambda kv: -kv[1])),
        "projetos": sorted(projetos, key=data_ord, reverse=True)[:60],
        "recentes": outros, "temas": temas,
        "fonte": f"{casa}, Processo Legislativo Eletrônico (consulta por autor)",
    }


def candidatos_do_municipio(doc: dict, municipio: str) -> list[dict]:
    alvo = " ".join(_normal(municipio))
    out = []
    for c in doc["candidatos"]:
        if c.get("situacao") == "desistiu":
            continue
        hist = (c.get("eleicoes_anteriores") or []) + [{"cargo": m.get("cargo"), "uf": m.get("cargo")} for m in c.get("mandatos") or []]
        if any("vereador" in (e.get("cargo") or "").lower() and alvo in " ".join(_normal(e.get("uf") or e.get("municipio") or "")) for e in hist):
            out.append(c)
    return out


def casar(c: dict, autores: dict[str, dict]) -> dict | None:
    for nome in (c.get("nome_urna"), c.get("nome_completo")):
        k = " ".join(_normal(nome or ""))
        if k and k in autores:
            return autores[k]
    # nome de urna contido no nome do autor (ex.: 'Karla Coser' em 'Karla Coser (Vereadora)')
    ku = " ".join(_normal(c.get("nome_urna") or ""))
    cands = [a for nome, a in autores.items() if ku and len(ku) >= 8 and (ku in nome or nome in ku)]
    return cands[0] if len(cands) == 1 else None


ANOS_MAX = 8   # lê ano a ano os últimos N anos com produção; cada ano cabe no teto de páginas


def baixar_autor(base: str, autor: dict) -> tuple[list[dict], int | None, str]:
    anos = sorted(autor.get("anos") or [])[-ANOS_MAX:]
    if not anos:
        return baixar_producao(base, autor["id"])
    itens, total, modos = [], 0, set()
    vistos = set()
    for ano in reversed(anos):
        its, tot, modo = baixar_producao(base, autor["id"], ano)
        modos.add(modo)
        total += tot or len(its)
        for i in its:
            if i.get("url") in vistos:
                continue
            vistos.add(i.get("url"))
            itens.append(i)
        aviso = "  (bateu no teto de páginas; suba --max-paginas)" if tot and len(its) < tot and len(its) >= MAX_PAGINAS * 100 - 100 else ""
        print(f"    {ano}: {len(its)} lidas de {tot or '?'}{aviso}", flush=True)
    return itens, total, "+".join(sorted(modos))


def main() -> int:
    global MAX_PAGINAS
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="https://camarasempapel.cmv.es.gov.br")
    ap.add_argument("--municipio", default="Vitória")
    ap.add_argument("--casa", default=None, help="nome da casa (padrão: Câmara Municipal de <municipio>)")
    ap.add_argument("--candidato", help="parte do nome, para testar um só")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-paginas", type=int, default=MAX_PAGINAS, help="teto de páginas de 100 por ano (padrão %(default)s)")
    a = ap.parse_args()
    MAX_PAGINAS = a.max_paginas
    casa = a.casa or f"Câmara Municipal de {a.municipio}"
    base = a.base.rstrip("/")

    doc = json.loads(CAND.read_text(encoding="utf-8"))
    raw, _ = _req(f"{base}/spl/consulta-autor.aspx")
    autores = listar_autores(decodificar(raw))
    if not autores:
        raise SystemExit("não achei a lista de autores em spl/consulta-autor.aspx; rode com DEBUG=1 e me mande a saída")
    print(f"{len(autores)} autores no portal da {casa}")

    alvo = candidatos_do_municipio(doc, a.municipio)
    if a.candidato:
        k = " ".join(_normal(a.candidato))
        alvo = [c for c in alvo if k in " ".join(_normal(c["nome_urna"])) or k in " ".join(_normal(c.get("nome_completo") or ""))]
    print(f"{len(alvo)} candidatos com passagem por vereador em {a.municipio}")
    feitos = sem = 0
    for c in alvo:
        autor = casar(c, autores)
        if not autor:
            sem += 1
            print(f"  sem autor no portal: {c['nome_urna']}")
            continue
        aid = autor["id"]
        print(f"  {c['nome_urna']} (autor {aid}, anos {', '.join(map(str, autor.get('anos') or [])) or '?'})", flush=True)
        try:
            itens, total, modo = baixar_autor(base, autor)
        except Exception as exc:  # noqa: BLE001
            print(f"  falhou {c['nome_urna']} (autor {aid}): {exc}", file=sys.stderr)
            continue
        c["camara_municipal"] = resumir(itens, total, base, aid, casa)
        r = c["camara_municipal"]
        feitos += 1
        print(f"    => {modo}: {r['total_lido']} lidas de {total or '?'}; projetos {len(r['projetos'])}; "
              + ", ".join(f"{k} {v}" for k, v in list(r["por_tipo"].items())[:4]))
        if not a.dry_run:
            CAND.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{feitos} candidatos com produção legislativa municipal; {sem} sem correspondência no portal")
    if not a.dry_run:
        print("gravado: data/candidatos.json. Agora rode: python3 scripts/build_bundle.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
