#!/usr/bin/env python3
"""Coleta dados públicos e atualiza data/candidatos.json.

Precisa de internet aberta para TSE, Câmara, Senado e Portal da Transparência.
NÃO foi executado no ambiente em que foi escrito (rede bloqueada). Rode primeiro
com --dry-run, leia o que ele imprime, e só depois deixe gravar. As funções de
normalização (normalizar_*) foram testadas com respostas de exemplo; as chamadas
de rede não.

Fontes e o que cada uma enche na ficha:

  --tse       DivulgaCand (ou, se a API der 403, os CSVs dos Dados Abertos do
              TSE, baixados para data/cache/): lista completa (ES + presidente), número, situação,
              foto, vice/suplentes, BENS declarados (com total), CERTIDÕES anexadas
              ao registro e ELEIÇÕES ANTERIORES (histórico eleitoral e trocas de
              partido). Cria ficha para quem ainda não está no JSON.
  --contas    DivulgaCandContas: total de receitas e despesas da campanha 2026 e
              maiores doadores.
  --camara    API da Câmara: projetos de autoria (situação), gastos da cota
              parlamentar por ano, órgãos/comissões, e o voto em cada item de
              data/votacoes_chave.json. Só para quem tem 'camara_id' ou é achado
              pelo nome.
  --senado    Dados abertos do Senado: autorias, relatorias, filiações e votos
              nas votações-chave. Só para quem tem 'senado_id' ou está em exercício.
  --emendas   Portal da Transparência: emendas parlamentares por autor (total e
              maiores destinos). Exige chave gratuita em
              https://portaldatransparencia.gov.br/api-de-dados/cadastrar-email
              na variável de ambiente PORTAL_TRANSPARENCIA_KEY.
  --links     Gera links de conferência (DivulgaCand, Câmara, Senado, Radar do
              Congresso, Comovotou, Jusbrasil). Não usa rede.
  --tudo      Todas as acima.

Sem API (fica manual no JSON): TCE-ES (contas de prefeito), Ales (produção
legislativa), gestão, fiscalização e processos.

Uso:
    python3 scripts/fetch_dados.py --tse --dry-run
    python3 scripts/fetch_dados.py --tudo
    python3 scripts/build_bundle.py
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAND_PATH = ROOT / "data" / "candidatos.json"
VOT_PATH = ROOT / "data" / "votacoes_chave.json"

TSE_BASE = "https://divulgacandcontas.tse.jus.br/divulga/rest/v1"
CAMARA_BASE = "https://dadosabertos.camara.leg.br/api/v2"
SENADO_BASE = "https://legis.senado.leg.br/dadosabertos"
PORTAL_BASE = "https://api.portaldatransparencia.gov.br/api-de-dados"

CARGOS_TSE = {
    "presidente": (1, "BR"),
    "governador": (3, "ES"),
    "senador": (5, "ES"),
    "deputado_federal": (6, "ES"),
    "deputado_estadual": (7, "ES"),
}
# O TSE responde 403 a clientes que não parecem navegador. Cabeçalhos de navegador resolvem na maioria dos casos.
UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer": "https://divulgacandcontas.tse.jus.br/divulga/",
    "Origin": "https://divulgacandcontas.tse.jus.br",
}
CACHE = ROOT / "data" / "cache"
TSE_CSV = {
    "consulta_cand": "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2026.zip",
    "bem_candidato": "https://cdn.tse.jus.br/estatistica/sead/odsele/bem_candidato/bem_candidato_2026.zip",
    "receitas": "https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_2026.zip",
}
CD_CARGO = {"1": "presidente", "3": "governador", "5": "senador", "6": "deputado_federal", "7": "deputado_estadual"}
HOJE = time.strftime("%Y-%m-%d")


# ============================================================ utilidades

def _curl(url: str, headers: dict, destino: pathlib.Path | None = None, timeout: int = 600) -> bytes | None:
    """Plano B: o TSE barra o TLS do Python (403) mas aceita o curl do sistema."""
    import shutil
    import subprocess
    if not shutil.which("curl"):
        return None
    cmd = ["curl", "-sSL", "--fail", "--max-time", str(timeout), "--compressed"]
    for k, v in headers.items():
        cmd += ["-H", f"{k}: {v}"]
    if destino:
        cmd += ["-o", str(destino)]
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout + 30)
    except Exception as exc:  # noqa: BLE001
        print(f"  curl falhou: {exc}", file=sys.stderr)
        return None
    if r.returncode != 0:
        print(f"  curl falhou ({r.returncode}): {r.stderr.decode(errors='ignore').strip()[:200]}", file=sys.stderr)
        return None
    return destino.read_bytes() if destino else r.stdout


def get_json(url: str, headers: dict | None = None, tentativas: int = 3, pausa: float = 0.6):
    h = dict(UA)
    if headers:
        h.update(headers)
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                raw = _curl(url, h)
                if raw:
                    try:
                        return json.loads(raw.decode("utf-8"))
                    except ValueError:
                        print(f"  resposta não é JSON: {url}", file=sys.stderr)
                        return None
            if i == tentativas - 1:
                print(f"  falhou: {url} ({exc})", file=sys.stderr)
                return None
            time.sleep(pausa * (2 ** i))
        except Exception as exc:  # noqa: BLE001
            if i == tentativas - 1:
                print(f"  falhou: {url} ({exc})", file=sys.stderr)
                return None
            time.sleep(pausa * (2 ** i))
    return None


def slug(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", str(txt or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", txt.lower()).strip("-")


def sem_titulo(nome: str) -> str:
    return re.sub(r"^(dr\.?|dra\.?|prof\.?|professora?|delegad[oa]|capit[aã]o|coronel|cabo|sargento|pastor|bispo|engenheiro)\s+", "", nome, flags=re.I)


def carregar():
    return json.loads(CAND_PATH.read_text(encoding="utf-8"))


def salvar(doc, dry_run: bool):
    if dry_run:
        print("(dry-run) não gravei nada")
        return
    CAND_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"gravado: {CAND_PATH.relative_to(ROOT)}")


def achar(cands, cargo, nome_urna):
    alvo = slug(nome_urna)
    alvo2 = slug(sem_titulo(nome_urna))
    for c in cands:
        if c["cargo"] == cargo and slug(c["nome_urna"]) in (alvo, alvo2):
            return c
    for c in cands:
        if c["cargo"] == cargo and slug(sem_titulo(c["nome_urna"])) == alvo2:
            return c
    return None


def brl(v):
    """Aceita '1.234,56' (bens, receitas), '1234.56' (complementar), números e vazio."""
    if v is None or v == "":
        return 0.0
    if not isinstance(v, str):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0
    t = v.strip().replace("R$", "").strip()
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return 0.0


# ============================================================ TSE: lista + detalhes

def id_eleicao_2026():
    data = get_json(f"{TSE_BASE}/eleicao/ordinarias") or []
    for e in data:
        if str(e.get("ano")) == "2026":
            return e["id"]
    return None


# ------------------------------------------------ fallback: CSVs dos Dados Abertos do TSE

def baixar_zip(nome: str) -> pathlib.Path | None:
    """Baixa (uma vez) o zip dos Dados Abertos para data/cache/ e devolve o caminho."""
    import shutil
    CACHE.mkdir(parents=True, exist_ok=True)
    dest = CACHE / f"{nome}_2026.zip"
    # aceita também o nome original do arquivo baixado do portal
    alternativos = {"receitas": ["prestacao_de_contas_eleitorais_candidatos_2026.zip", "receitas_candidatos_2026.zip"]}
    for alt in alternativos.get(nome, []):
        if (CACHE / alt).exists() and (CACHE / alt).stat().st_size > 0:
            return CACHE / alt
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    url = TSE_CSV[nome]
    print(f"  baixando {url} (pode levar minutos)")
    h = {"User-Agent": UA["User-Agent"], "Accept": "*/*", "Accept-Language": UA["Accept-Language"], "Referer": "https://dadosabertos.tse.jus.br/"}
    try:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=600) as resp, open(dest, "wb") as fh:
            shutil.copyfileobj(resp, fh)
        return dest
    except Exception as exc:  # noqa: BLE001
        print(f"  urllib falhou ({exc}); tentando com curl", file=sys.stderr)
        dest.unlink(missing_ok=True)
    if _curl(url, h, destino=dest) and dest.exists() and dest.stat().st_size > 1000:
        return dest
    dest.unlink(missing_ok=True)
    print(f"  falhou também com curl: {url}", file=sys.stderr)
    return None


def ler_csv_zip(zip_path: pathlib.Path, sufixos: tuple[str, ...]):
    """Itera as linhas (dict) dos CSVs do zip cujo nome termina com um dos sufixos (ex.: _ES.csv, _BR.csv)."""
    import csv
    import io
    import zipfile
    with zipfile.ZipFile(zip_path) as z:
        for nome in z.namelist():
            if not nome.lower().endswith(".csv") or not any(nome.upper().endswith(s.upper()) for s in sufixos):
                continue
            with z.open(nome) as fh:
                texto = io.TextIOWrapper(fh, encoding="latin-1", newline="")
                for row in csv.DictReader(texto, delimiter=";"):
                    yield row


def normalizar_csv_candidato(row: dict) -> dict | None:
    """Uma linha de consulta_cand_2026_XX.csv -> campos da ficha. None se não for cargo titular."""
    cargo = CD_CARGO.get(str(row.get("CD_CARGO", "")).strip())
    if not cargo:
        return None
    detalhe = (row.get("DS_DETALHE_SITUACAO_CAND") or row.get("DS_SITUACAO_CANDIDATURA") or "")
    idade = row.get("NR_IDADE_DATA_POSSE")
    return {
        "cargo": cargo,
        "nome_urna": (row.get("NM_URNA_CANDIDATO") or "").strip().title() if (row.get("NM_URNA_CANDIDATO") or "").isupper() else (row.get("NM_URNA_CANDIDATO") or "").strip(),
        "nome_completo": (row.get("NM_CANDIDATO") or "").strip().title(),
        "numero": (row.get("NR_CANDIDATO") or "").strip() or None,
        "partido": (row.get("SG_PARTIDO") or "").strip() or None,
        "situacao": mapear_situacao(detalhe),
        "situacao_detalhe": detalhe.strip().capitalize() or None,
        "idade": int(idade) if idade and idade.strip().isdigit() and int(idade) > 0 else None,
        "ocupacao": (row.get("DS_OCUPACAO") or "").strip().capitalize() or None,
        "tse_id": (row.get("SQ_CANDIDATO") or "").strip() or None,
        "federacao": (row.get("NM_FEDERACAO") or "").strip() if (row.get("NM_FEDERACAO") or "").strip() not in ("", "#NULO#", "#NE#") else None,
        "coligacao": (row.get("NM_COLIGACAO") or "").strip() if (row.get("NM_COLIGACAO") or "").strip() not in ("", "#NULO#", "#NE#") else None,
    }


def normalizar_csv_bens(rows) -> dict:
    """Linhas de bem_candidato -> {SQ_CANDIDATO: {"total":..., "itens":[...]}}"""
    por = {}
    for r in rows:
        sq = (r.get("SQ_CANDIDATO") or "").strip()
        if not sq:
            continue
        item = {"tipo": (r.get("DS_TIPO_BEM_CANDIDATO") or "").strip().capitalize(), "descricao": (r.get("DS_BEM_CANDIDATO") or "").strip()[:160], "valor": brl(r.get("VR_BEM_CANDIDATO"))}
        b = por.setdefault(sq, {"total": 0.0, "itens": []})
        b["total"] += item["valor"]
        b["itens"].append(item)
    for b in por.values():
        b["itens"] = sorted(b["itens"], key=lambda i: -i["valor"])[:15]
        b["fonte"] = "TSE Dados Abertos (bem_candidato_2026)"
        b["atualizado_em"] = HOJE
    return por


def normalizar_csv_receitas(rows) -> dict:
    """Linhas de receitas_candidatos -> {SQ_CANDIDATO: campanha}"""
    por = {}
    for r in rows:
        sq = (r.get("SQ_CANDIDATO") or "").strip()
        if not sq:
            continue
        v = brl(r.get("VR_RECEITA"))
        nome = (r.get("NM_DOADOR") or r.get("NM_DOADOR_RFB") or "não identificado").strip()
        origem = (r.get("DS_ORIGEM_RECEITA") or r.get("DS_FONTE_RECEITA") or "").lower()
        c = por.setdefault(sq, {"receitas": 0.0, "despesas": None, "fundo_publico_e_partido": 0.0, "_doadores": {}})
        c["receitas"] += v
        if "fundo" in origem or "partid" in origem or "fundo" in nome.lower() or "direção" in nome.lower():
            c["fundo_publico_e_partido"] += v
        c["_doadores"][nome] = c["_doadores"].get(nome, 0.0) + v
    for c in por.values():
        c["maiores_doadores"] = [{"nome": k, "valor": round(v, 2)} for k, v in sorted(c.pop("_doadores").items(), key=lambda kv: -kv[1])[:10]]
        c["fonte"] = "TSE Dados Abertos (receitas_candidatos_2026)"
        c["atualizado_em"] = HOJE
    return por


ID_ELEICAO = {"BR": "6257", "ES": "6259"}  # CD_ELEICAO de 2026 nos CSVs; é o id que o DivulgaCand usa na URL


def limpo(v) -> str | None:
    v = (v or "").strip()
    return None if v in ("", "#NULO#", "#NE#", "#NULO", "#NE", "-1", "-3") else v


def normalizar_csv_historico(rows) -> dict:
    """historico_candidatura -> {SQ_CANDIDATO_ATUAL: {eleicoes_anteriores, trocas_de_partido, vezes_eleito, primeiro_ano}}"""
    por = {}
    for r in rows:
        sq = limpo(r.get("SQ_CANDIDATO_ATUAL"))
        ano = limpo(r.get("ANO_ELEICAO"))
        if not sq or not ano or ano == limpo(r.get("ANO_ELEICAO_ATUAL")):
            continue
        chave = (ano, limpo(r.get("DS_CARGO")), limpo(r.get("NM_UE")))
        item = {"ano": ano, "cargo": (limpo(r.get("DS_CARGO")) or "").title(), "partido": limpo(r.get("SG_PARTIDO")),
                "uf": (limpo(r.get("NM_UE")) or "").title(), "resultado": limpo(r.get("DS_SIT_TOT_TURNO")), "turno": limpo(r.get("NR_TURNO")),
                "situacao": limpo(r.get("DS_SITUACAO_CANDIDATURA"))}
        d = por.setdefault(sq, {})
        atual = d.get(chave)
        if not atual or (item["turno"] or "1") > (atual["turno"] or "1"):  # 2º turno manda no resultado
            d[chave] = item
    out = {}
    for sq, d in por.items():
        lista = sorted(d.values(), key=lambda x: (x["ano"], x["cargo"]))
        partidos = [x["partido"] for x in lista if x["partido"]]
        trocas = sum(1 for i in range(1, len(partidos)) if partidos[i] != partidos[i - 1])
        eleitos = [x for x in lista if (x["resultado"] or "").lower().startswith("eleito")]
        out[sq] = {"eleicoes_anteriores": lista, "trocas_de_partido": trocas, "vezes_eleito": len(eleitos),
                   "primeiro_ano": int(lista[0]["ano"]) if lista else None, "eleitos": eleitos}
    return out


def normalizar_csv_motivos(rows) -> dict:
    por = {}
    for r in rows:
        sq = limpo(r.get("SQ_CANDIDATO"))
        if not sq:
            continue
        por.setdefault(sq, []).append({"tipo": limpo(r.get("DS_TP_MOTIVO")), "motivo": limpo(r.get("DS_MOTIVO")), "processo": limpo(r.get("NR_PROCESSO"))})
    return por


def normalizar_csv_complementar(rows) -> dict:
    por = {}
    for r in rows:
        sq = limpo(r.get("SQ_CANDIDATO"))
        if not sq:
            continue
        por[sq] = {
            "reeleicao": (limpo(r.get("ST_REELEICAO")) or "").upper() == "S",
            "limite_gastos": brl(limpo(r.get("VR_DESPESA_MAX_CAMPANHA"))) if limpo(r.get("VR_DESPESA_MAX_CAMPANHA")) else None,
            "situacao_tot": limpo(r.get("DS_SITUACAO_CANDIDATO_TOT")),
            "situacao_julgamento": limpo(r.get("DS_SITUACAO_JULGAMENTO")),
            "na_urna": (limpo(r.get("ST_CANDIDATO_INSERIDO_URNA")) or "").upper() == "SIM",
            "destinacao_votos": limpo(r.get("NM_TIPO_DESTINACAO_VOTOS")),
            "substituido": (limpo(r.get("ST_SUBSTITUIDO")) or "").upper() == "S",
            "sq_substituido": limpo(r.get("SQ_SUBSTITUIDO")),
            "nascimento": (limpo(r.get("NM_MUNICIPIO_NASCIMENTO")) or "").title() or None,
            "genero": (limpo(r.get("DS_GENERO_FEFC")) or "").capitalize() or None,
            "cor_raca": (limpo(r.get("DS_COR_RACA_FEFC")) or "").capitalize() or None,
            "declarou_bens": (limpo(r.get("ST_DECLARAR_BENS")) or "").upper() == "S",
            "processo_registro": limpo(r.get("NR_PROCESSO")),
        }
    return por


def normalizar_csv_redes(rows) -> dict:
    por = {}
    for r in rows:
        sq = limpo(r.get("SQ_CANDIDATO"))
        url = limpo(r.get("DS_URL"))
        if not sq or not url:
            continue
        u = url.strip()
        # o TSE grava alguns em caixa alta; para rede social, minúsculas funcionam
        if u == u.upper():
            u = u.lower()
        if not re.match(r"^https?://", u, re.I):
            u = "https://" + u
        por.setdefault(sq, []).append(u)
    return por


def mapear_situacao_tot(tot: str | None, destinacao: str | None) -> tuple[str, str | None]:
    t = (tot or "").upper()
    obs = None
    if "INDEFERIDO" in t:
        sit = "indeferido"
        obs = "Indeferido com recurso: aparece na urna, votos ficam sub judice." if "RECURSO" in t else "Registro indeferido."
    elif "DEFERIDO" in t:
        sit = "deferido"
        if "RECURSO" in t:
            obs = "Deferido, mas há recurso pendente contra o registro."
    elif "RENÚNCIA" in t or "RENUNCIA" in t or "FALECIDO" in t or "CASSADO" in t:
        sit = "desistiu"
        obs = t.capitalize()
    else:
        sit = "aguardando"
        obs = t.capitalize() if t else None
    if destinacao and "anulado" in destinacao.lower():
        obs = (obs + " " if obs else "") + f"Destinação dos votos: {destinacao}."
    return sit, obs


def aplicar_extras_csv(doc):
    """Aplica historico, motivos, complementar e redes sociais, se os zips estiverem em data/cache/."""
    por_sq = {str(c.get("tse_id")): c for c in doc["candidatos"] if c.get("tse_id")}
    for c in por_sq.values():
        uf = "BR" if c["cargo"] == "presidente" else "ES"
        c["tse_url"] = f"https://divulgacandcontas.tse.jus.br/divulga/#/candidato/2026/{ID_ELEICAO[uf]}/{uf}/{c['tse_id']}"

    zh = CACHE / "historico_candidatura_2026.zip"
    if zh.exists():
        hist = normalizar_csv_historico(ler_csv_zip(zh, ("_ES.csv", "_BR.csv")))
        n = 0
        for sq, h in hist.items():
            c = por_sq.get(sq)
            if not c:
                continue
            c["eleicoes_anteriores"] = h["eleicoes_anteriores"]
            c["trocas_de_partido"] = h["trocas_de_partido"]
            c["vezes_eleito"] = h["vezes_eleito"]
            if not c.get("inicio_politica") and h["primeiro_ano"]:
                c["inicio_politica"] = h["primeiro_ano"]
            if c.get("tipo_historico") == "sem_dados":
                if h["eleitos"]:
                    cargos = " ".join((e["cargo"] or "").lower() for e in h["eleitos"])
                    exec_ = any(k in cargos for k in ("prefeito", "governador", "vice"))
                    leg = any(k in cargos for k in ("vereador", "deputad", "senador"))
                    c["tipo_historico"] = "misto" if exec_ and leg else "executivo" if exec_ else "legislativo"
                    if not c.get("mandatos"):
                        c["mandatos"] = [{"cargo": f"{e['cargo']} ({e['uf']})", "periodo": f"eleito em {e['ano']}", "partido": e["partido"], "obs": "importado do histórico do TSE; período e detalhes a confirmar"} for e in h["eleitos"]]
                else:
                    c["tipo_historico"] = "sem_mandato"
                    c["resumo"] = c["resumo"].replace("histórico ainda não pesquisado.", f"Disputou {len(h['eleicoes_anteriores'])} eleição(ões) antes sem ser eleito, segundo o TSE.")
            n += 1
        print(f"  histórico eleitoral aplicado a {n} candidatos")

    zm = CACHE / "motivo_cassacao_2026.zip"
    if zm.exists():
        mot = normalizar_csv_motivos(ler_csv_zip(zm, ("_ES.csv", "_BR.csv")))
        n = 0
        for sq, lista in mot.items():
            c = por_sq.get(sq)
            if not c:
                continue
            c["motivos_registro"] = lista
            txt = "; ".join(f"{m['motivo']}" + (f" (processo {m['processo']})" if m.get("processo") else "") for m in lista if m.get("motivo"))
            if txt and txt not in (c.get("situacao_obs") or ""):
                c["situacao_obs"] = ((c.get("situacao_obs") or "") + " Motivo registrado pelo TSE: " + txt + ".").strip()
            n += 1
        print(f"  motivos de indeferimento/cassação aplicados a {n} candidatos")

    zc = CACHE / "consulta_cand_complementar_2026.zip"
    if zc.exists():
        comp = normalizar_csv_complementar(ler_csv_zip(zc, ("_ES.csv", "_BR.csv")))
        n = 0
        for sq, k in comp.items():
            c = por_sq.get(sq)
            if not c:
                continue
            sit, obs = mapear_situacao_tot(k["situacao_tot"], k["destinacao_votos"])
            c["situacao"] = sit
            if obs and obs not in (c.get("situacao_obs") or ""):
                c["situacao_obs"] = ((c.get("situacao_obs") or "") + " " + obs).strip()
            if k["reeleicao"]:
                c["reeleicao"] = True
            c["tse_complementar"] = {kk: v for kk, v in k.items() if kk not in ("situacao_tot", "reeleicao")}
            n += 1
        print(f"  dados complementares aplicados a {n} candidatos")

    zr = CACHE / "rede_social_candidato_2026.zip"
    if zr.exists():
        redes = normalizar_csv_redes(ler_csv_zip(zr, ("_ES.csv", "_BR.csv")))
        n = 0
        for sq, lista in redes.items():
            c = por_sq.get(sq)
            if c:
                c["redes"] = lista
                n += 1
        print(f"  redes sociais aplicadas a {n} candidatos")

    # certidões e propostas de governo: zips de PDFs; guardamos o nome do arquivo por candidato
    for nome_zip, campo in (("certidao_criminal_2026_ES.zip", "certidoes_arquivos"), ("proposta_governo_2026_ES.zip", "proposta_governo_arquivos")):
        zz = CACHE / nome_zip
        if not zz.exists():
            continue
        import zipfile
        n = 0
        with zipfile.ZipFile(zz) as z:
            for nome in z.namelist():
                m = re.search(r"(\d{11,12})", nome)
                c = por_sq.get(m.group(1)) if m else None
                if c:
                    c.setdefault(campo, []).append(f"data/cache/{nome_zip}:{nome}")
                    n += 1
        print(f"  {campo}: {n} arquivos mapeados")


def fetch_tse_csv(doc, dry_run: bool):
    print("  API bloqueada (403). Usando os CSVs dos Dados Abertos do TSE.")
    z = baixar_zip("consulta_cand")
    if not z:
        raise SystemExit("não consegui baixar consulta_cand_2026.zip; baixe à mão em dadosabertos.tse.jus.br e salve em data/cache/")
    bens = {}
    zb = baixar_zip("bem_candidato")
    if zb:
        bens = normalizar_csv_bens(ler_csv_zip(zb, ("_ES.csv", "_BR.csv")))
    novos = atualizados = vistos = 0
    for row in ler_csv_zip(z, ("_ES.csv", "_BR.csv")):
        n = normalizar_csv_candidato(row)
        if not n:
            continue
        if n["cargo"] == "presidente" and (row.get("SG_UF") or "").strip() != "BR":
            continue
        if n["cargo"] != "presidente" and (row.get("SG_UF") or "").strip() != "ES":
            continue
        vistos += 1
        alvo = achar(doc["candidatos"], n["cargo"], n["nome_urna"])
        b = bens.get(n["tse_id"])
        uf_link = "BR" if n["cargo"] == "presidente" else "ES"
        n["tse_url"] = f"https://divulgacandcontas.tse.jus.br/divulga/#/candidato/2026/{ID_ELEICAO[uf_link]}/{uf_link}/{n['tse_id']}"
        if alvo:
            for k in ("numero", "situacao", "situacao_detalhe", "tse_id", "tse_url", "idade", "ocupacao"):
                if n.get(k) and (k in ("situacao", "situacao_detalhe", "tse_id", "tse_url") or not alvo.get(k)):
                    alvo[k] = n[k]
            if b:
                alvo["bens"] = b
            atualizados += 1
        else:
            doc["candidatos"].append({
                "id": slug(n["nome_urna"]) + ("-" + n["numero"] if n["numero"] else ""), "cargo": n["cargo"], "nome_urna": n["nome_urna"],
                "nome_completo": n["nome_completo"], "partido": n["partido"], "numero": n["numero"], "idade": n["idade"], "ocupacao": n["ocupacao"],
                "situacao": n["situacao"], "situacao_obs": n["situacao_detalhe"], "tipo_historico": "sem_dados", "inicio_politica": None,
                "resumo": "Importado do TSE (Dados Abertos); histórico ainda não pesquisado." + (f" Federação: {n['federacao']}." if n.get("federacao") else "") + (f" Coligação: {n['coligacao']}." if n.get("coligacao") else ""),
                "mandatos": [], "projetos": None, "gestao": [], "relatorias": [], "fiscalizacao": [], "processos": [],
                "bens": b, "certidoes": [], "eleicoes_anteriores": [], "tse_id": n["tse_id"], "tse_url": n["tse_url"],
                "fontes": ["https://dadosabertos.tse.jus.br/dataset/candidatos-2026"],
            })
            novos += 1
    doc["meta"]["atualizado_em_tse"] = HOJE
    doc["meta"]["fonte_tse"] = "Dados Abertos (CSV)"
    print(f"TSE CSV: {vistos} candidatos lidos, {atualizados} atualizados, {novos} novos")
    orfaos = [c["nome_urna"] for c in doc["candidatos"] if not c.get("tse_id")]
    if orfaos:
        print(f"  fichas já existentes que NÃO casaram com nenhum nome do TSE ({len(orfaos)}): {', '.join(orfaos)}")
        print("  -> confira o nome de urna no CSV e ajuste 'nome_urna' no JSON, ou preencha 'tse_id' à mão")
    aplicar_extras_csv(doc)
    _atualizar_cobertura(doc)
    salvar(doc, dry_run)


def _atualizar_cobertura(doc):
    from collections import Counter
    cont = Counter(c["cargo"] for c in doc["candidatos"] if c.get("situacao") != "desistiu")
    doc["meta"]["cobertura"] = {cargo: f"{n} candidatos importados do TSE em {HOJE}" for cargo, n in cont.items()}


def mapear_situacao(txt: str) -> str:
    t = (txt or "").lower()
    if "indeferido" in t:
        return "indeferido"
    if "deferido" in t or "apto" in t:
        return "deferido"
    if "renúncia" in t or "renuncia" in t or "desist" in t or "cassad" in t:
        return "desistiu"
    return "aguardando"


def normalizar_tse_detalhe(det: dict) -> dict:
    """Extrai bens, certidões e eleições anteriores do JSON de /candidatura/buscar."""
    bens = []
    for b in det.get("bens") or []:
        bens.append({"tipo": b.get("descricaoDeTipoDeBem") or b.get("descricao"), "descricao": (b.get("descricao") or "")[:160], "valor": brl(b.get("valor"))})
    total = brl(det.get("totalDeBens")) or sum(b["valor"] for b in bens)
    certidoes = []
    for a in det.get("arquivos") or []:
        nome = (a.get("nome") or a.get("descricao") or "").lower()
        if "certid" in nome or "crimin" in nome or "quita" in nome:
            certidoes.append({"nome": a.get("nome") or a.get("descricao"), "url": a.get("url")})
    anteriores = []
    for e in det.get("eleicoesAnteriores") or []:
        anteriores.append({
            "ano": e.get("nrAno") or e.get("ano"),
            "cargo": e.get("cargo") or e.get("nomeCargo"),
            "partido": (e.get("partido") or {}).get("sigla") if isinstance(e.get("partido"), dict) else e.get("sgPartido") or e.get("partido"),
            "uf": e.get("sgUe") or e.get("sgUf"),
            "resultado": e.get("situacaoTotalizacao") or e.get("descricaoSituacao") or e.get("resultado"),
            "votos": e.get("votos") or e.get("qtVotos"),
        })
    anteriores.sort(key=lambda x: str(x.get("ano") or ""))
    partidos = [a["partido"] for a in anteriores if a.get("partido")]
    trocas = sum(1 for i in range(1, len(partidos)) if partidos[i] != partidos[i - 1])
    return {
        "bens": {"total": total, "itens": sorted(bens, key=lambda b: -b["valor"])[:15], "fonte": "TSE DivulgaCand", "atualizado_em": HOJE},
        "certidoes": certidoes,
        "eleicoes_anteriores": anteriores,
        "trocas_de_partido": trocas,
        "vices": [(v.get("nomeUrna") or v.get("nm")) for v in (det.get("vices") or [])],
        "foto": det.get("fotoUrl"),
        "situacao": mapear_situacao(det.get("descricaoSituacao") or det.get("descricaoTotalizacao") or ""),
        "numero": str(det.get("numero")) if det.get("numero") else None,
        "partido": (det.get("partido") or {}).get("sigla"),
        "idade": det.get("idade") or None,
        "ocupacao": det.get("ocupacao") or None,
        "nome_completo": det.get("nomeCompleto"),
    }


def fetch_tse(doc, dry_run: bool):
    id_el = id_eleicao_2026()
    if not id_el:
        return fetch_tse_csv(doc, dry_run)
    novos = atualizados = 0
    for cargo, (cod, uf) in CARGOS_TSE.items():
        lista = get_json(f"{TSE_BASE}/candidatura/listar/2026/{uf}/{id_el}/{cod}/candidatos")
        if not lista or "candidatos" not in lista:
            print(f"  {cargo}: sem resposta", file=sys.stderr)
            continue
        for c in lista["candidatos"]:
            nome_urna = c.get("nomeUrna") or c.get("nomeCompleto")
            alvo = achar(doc["candidatos"], cargo, nome_urna)
            det = get_json(f"{TSE_BASE}/candidatura/buscar/2026/{uf}/{id_el}/candidato/{c.get('id')}") or {}
            n = normalizar_tse_detalhe(det) if det else {"situacao": mapear_situacao(c.get("descricaoSituacao") or ""), "numero": str(c.get("numero")) if c.get("numero") else None, "partido": (c.get("partido") or {}).get("sigla"), "foto": c.get("fotoUrl")}
            n["tse_id"] = c.get("id")
            n["tse_url"] = f"https://divulgacandcontas.tse.jus.br/divulga/#/candidato/2026/{id_el}/{uf}/{c.get('id')}"
            if alvo:
                for k, v in n.items():
                    if v in (None, "", [], {}):
                        continue
                    if k in ("situacao", "tse_id", "tse_url", "foto", "bens", "certidoes", "eleicoes_anteriores", "trocas_de_partido") or not alvo.get(k):
                        alvo[k] = v
                if n.get("vices") and alvo.get("chapa") and not alvo["chapa"].get("vice"):
                    alvo["chapa"]["vice"] = n["vices"][0]
                atualizados += 1
            else:
                doc["candidatos"].append({
                    "id": slug(nome_urna), "cargo": cargo, "nome_urna": nome_urna,
                    "nome_completo": n.get("nome_completo") or c.get("nomeCompleto"), "partido": n.get("partido"),
                    "numero": n.get("numero"), "idade": n.get("idade"), "ocupacao": n.get("ocupacao"),
                    "situacao": n.get("situacao"), "tipo_historico": "sem_dados", "inicio_politica": None,
                    "resumo": "Importado do TSE; histórico ainda não pesquisado.",
                    "mandatos": [], "projetos": None, "gestao": [], "relatorias": [], "fiscalizacao": [], "processos": [],
                    "bens": n.get("bens"), "certidoes": n.get("certidoes", []), "eleicoes_anteriores": n.get("eleicoes_anteriores", []),
                    "trocas_de_partido": n.get("trocas_de_partido"), "foto": n.get("foto"), "tse_id": n["tse_id"], "tse_url": n["tse_url"],
                    "fontes": [n["tse_url"]],
                })
                novos += 1
            time.sleep(0.2)
        print(f"  {cargo}: {len(lista['candidatos'])} no TSE")
    doc["meta"]["atualizado_em_tse"] = HOJE
    doc["meta"]["id_eleicao_tse"] = id_el
    print(f"TSE: {atualizados} atualizados, {novos} novos")
    salvar(doc, dry_run)


# ============================================================ TSE: prestação de contas

def normalizar_contas(resumo: dict, receitas: list) -> dict:
    """resumo = /prestador/consulta/...; receitas = lista de doações."""
    doadores = {}
    for r in receitas or []:
        nome = r.get("nomeDoador") or r.get("nome") or "não identificado"
        doadores[nome] = doadores.get(nome, 0.0) + brl(r.get("valor") or r.get("valorReceita"))
    top = sorted(doadores.items(), key=lambda kv: -kv[1])[:10]
    fundo = sum(v for k, v in doadores.items() if "fundo" in k.lower() or "direção" in k.lower() or "partid" in k.lower())
    total_rec = brl((resumo.get("dadosConsolidados") or {}).get("totalRecebido")) or brl(resumo.get("totalRecebido")) or sum(doadores.values())
    total_desp = brl((resumo.get("dadosConsolidados") or {}).get("totalDespesasPagas")) or brl(resumo.get("totalDespesas"))
    return {"receitas": total_rec, "despesas": total_desp, "fundo_publico_e_partido": fundo,
            "maiores_doadores": [{"nome": k, "valor": v} for k, v in top], "fonte": "TSE DivulgaCandContas", "atualizado_em": HOJE}


def fetch_contas_csv(doc, dry_run: bool):
    print("  API bloqueada. Usando o CSV de prestação de contas dos Dados Abertos (arquivo grande, centenas de MB).")
    z = baixar_zip("receitas")
    if not z:
        return
    por = normalizar_csv_receitas(ler_csv_zip(z, ("receitas_candidatos_2026_ES.csv", "receitas_candidatos_2026_BR.csv")))
    n = 0
    for c in doc["candidatos"]:
        camp = por.get(str(c.get("tse_id") or ""))
        if camp:
            c["campanha"] = camp
            n += 1
    print(f"  contas preenchidas para {n} candidatos")
    salvar(doc, dry_run)


def fetch_contas(doc, dry_run: bool):
    id_el = doc["meta"].get("id_eleicao_tse") or id_eleicao_2026()
    if not id_el:
        return fetch_contas_csv(doc, dry_run)
    for c in doc["candidatos"]:
        if not c.get("tse_id") or not c.get("numero"):
            continue
        cod, uf = CARGOS_TSE[c["cargo"]]
        base = f"{TSE_BASE}/prestador/consulta/2026/{id_el}/{uf}/{cod}/{urllib.parse.quote(c['partido'])}/{c['numero']}/{c['tse_id']}"
        resumo = get_json(base) or {}
        receitas = get_json(base.replace("/consulta/", "/consulta/receitas/")) or []
        if not resumo and not receitas:
            continue
        c["campanha"] = normalizar_contas(resumo, receitas if isinstance(receitas, list) else receitas.get("receitas", []))
        print(f"  {c['nome_urna']}: R$ {c['campanha']['receitas']:,.0f} recebidos")
        time.sleep(0.2)
    salvar(doc, dry_run)


# ============================================================ Câmara

def camara_id_por_nome(c):
    for nome in (c.get("nome_completo"), c["nome_urna"], sem_titulo(c["nome_urna"])):
        if not nome:
            continue
        data = get_json(f"{CAMARA_BASE}/deputados?nome={urllib.parse.quote(nome)}&siglaUf=ES&ordem=ASC&ordenarPor=nome")
        if data and data.get("dados"):
            return data["dados"][0]["id"]
    return None


def paginar_camara(url):
    out, pagina = [], 1
    while True:
        data = get_json(f"{url}&itens=100&pagina={pagina}")
        if not data or not data.get("dados"):
            break
        out.extend(data["dados"])
        if not any(l.get("rel") == "next" for l in data.get("links", [])):
            break
        pagina += 1
    return out


def normalizar_proposicoes(props: list, detalhes: dict) -> dict:
    aprovados, tramitando, arquivados = [], [], 0
    for p in props:
        det = detalhes.get(p["id"]) or {}
        st = det.get("statusProposicao", {})
        desc = (st.get("descricaoSituacao") or "").lower()
        item = {"id": f"{p['siglaTipo']} {p['numero']}/{p['ano']}", "titulo": (det.get("ementa") or p.get("ementa") or "")[:240]}
        if "transformad" in desc and "norma" in desc:
            item.update({"norma": st.get("despacho") or "transformado em norma jurídica", "ano": p["ano"], "status": "em vigor", "papel": "autor"})
            aprovados.append(item)
        elif "arquivad" in desc:
            arquivados += 1
        else:
            item["obs"] = st.get("descricaoSituacao") or st.get("descricaoTramitacao")
            tramitando.append(item)
    return {"apresentados": {"total": len(props), "obs": f"{arquivados} arquivadas. Só PL, PLP e PEC de autoria própria."},
            "em_tramitacao": tramitando, "aprovados": aprovados}


def normalizar_despesas(desp: list) -> dict:
    por_ano = {}
    for d in desp:
        ano = str(d.get("ano"))
        por_ano[ano] = por_ano.get(ano, 0.0) + brl(d.get("valorLiquido") or d.get("valorDocumento"))
    return {"cota_parlamentar_por_ano": {k: round(v, 2) for k, v in sorted(por_ano.items())}, "fonte": "Câmara, API dadosabertos (despesas)", "atualizado_em": HOJE}


def resolver_votacoes_camara(item):
    q = f"{CAMARA_BASE}/proposicoes?siglaTipo={item['tipo']}&numero={item['numero']}&ano={item['ano']}"
    data = get_json(q)
    if not data or not data.get("dados"):
        return []
    pid = data["dados"][0]["id"]
    vot = get_json(f"{CAMARA_BASE}/proposicoes/{pid}/votacoes?ordem=DESC&ordenarPor=dataHoraRegistro") or {}
    out = []
    for v in vot.get("dados", []):
        if not v.get("aprovacao") in (0, 1, True, False, None):
            continue
        votos = get_json(f"{CAMARA_BASE}/votacoes/{v['id']}/votos") or {}
        out.append({"id": v["id"], "data": v.get("data"), "descricao": v.get("descricao"), "votos": {x["deputado_"]["id"]: x["tipoVoto"] for x in votos.get("dados", []) if x.get("deputado_")}})
        time.sleep(0.15)
    return out


def fetch_camara(doc, dry_run: bool):
    itens = json.loads(VOT_PATH.read_text(encoding="utf-8"))["camara"]
    votacoes = []
    for it in itens:
        print(f"  votação: {it['tema']}")
        for v in resolver_votacoes_camara(it):
            votacoes.append((it, v))
    for c in doc["candidatos"]:
        foi_federal = any("federal" in (m.get("cargo") or "").lower() and "deputad" in (m.get("cargo") or "").lower() for m in c.get("mandatos", []))
        if not foi_federal and not c.get("camara_id"):
            continue
        dep_id = c.get("camara_id") or camara_id_por_nome(c)
        if not dep_id:
            print(f"  {c['nome_urna']}: não achei na Câmara", file=sys.stderr)
            continue
        c["camara_id"] = dep_id
        props = paginar_camara(f"{CAMARA_BASE}/proposicoes?idDeputadoAutor={dep_id}&siglaTipo=PL&siglaTipo=PLP&siglaTipo=PEC&ordem=ASC&ordenarPor=id")
        detalhes = {}
        for p in props:
            d = get_json(f"{CAMARA_BASE}/proposicoes/{p['id']}")
            if d:
                detalhes[p["id"]] = d["dados"]
            time.sleep(0.12)
        c["projetos"] = {"fonte": f"Câmara dos Deputados, API dadosabertos (deputado {dep_id})", "atualizado_em": HOJE, **normalizar_proposicoes(props, detalhes)}
        desp = paginar_camara(f"{CAMARA_BASE}/deputados/{dep_id}/despesas?ordem=ASC&ordenarPor=ano")
        c["gastos"] = normalizar_despesas(desp)
        orgaos = get_json(f"{CAMARA_BASE}/deputados/{dep_id}/orgaos?itens=100") or {}
        c["comissoes"] = [{"sigla": o.get("siglaOrgao"), "nome": o.get("nomeOrgao"), "papel": o.get("titulo"), "inicio": o.get("dataInicio"), "fim": o.get("dataFim")} for o in orgaos.get("dados", [])]
        c["votacoes_chave"] = [{"tema": it["tema"], "quando": it["quando"], "data": v["data"], "descricao": v["descricao"], "voto": v["votos"].get(dep_id)} for it, v in votacoes if dep_id in v["votos"]]
        print(f"  {c['nome_urna']}: {len(props)} proposições, {len(c['projetos']['aprovados'])} leis, {len(c['votacoes_chave'])} votos-chave, {len(c['comissoes'])} comissões")
    salvar(doc, dry_run)


# ============================================================ Senado

def normalizar_senado_autorias(autorias: list, situacoes: dict) -> dict:
    aprovados, tramitando, total = [], [], 0
    for a in autorias:
        m = a.get("Materia") or {}
        if m.get("SiglaSubtipoMateria") not in ("PL", "PLS", "PLP", "PEC", "PLC"):
            continue
        total += 1
        desc = json.dumps(situacoes.get(m.get("CodigoMateria"), {}), ensure_ascii=False).lower()
        item = {"id": f"{m.get('SiglaSubtipoMateria')} {m.get('NumeroMateria')}/{m.get('AnoMateria')}", "titulo": (m.get("DescricaoIdentificacaoMateria") or m.get("Ementa") or "")[:240]}
        if "norma" in desc and ("transformad" in desc or "promulgad" in desc):
            item.update({"norma": "transformado em norma", "ano": m.get("AnoMateria"), "status": "em vigor", "papel": "autor"})
            aprovados.append(item)
        elif "arquivad" in desc:
            continue
        else:
            tramitando.append(item)
    return {"apresentados": {"total": total, "obs": "Só PL, PLS, PLP e PEC de autoria."}, "em_tramitacao": tramitando, "aprovados": aprovados}


def normalizar_senado_relatorias(rels: list) -> list:
    out = []
    for r in rels:
        m = r.get("Materia") or {}
        if m.get("SiglaSubtipoMateria") not in ("PL", "PLS", "PLP", "PEC", "PLC", "MPV"):
            continue
        out.append({"titulo": f"{m.get('SiglaSubtipoMateria')} {m.get('NumeroMateria')}/{m.get('AnoMateria')}: {(m.get('Ementa') or '')[:160]}",
                    "resultado": (r.get("DescricaoTipoRelator") or "relator") + (" · " + (r.get("Comissao") or {}).get("SiglaComissao", "") if r.get("Comissao") else ""),
                    "ano": m.get("AnoMateria")})
    return out


def normalizar_senado_filiacoes(fil: list) -> list:
    return [{"partido": (f.get("Partido") or {}).get("SiglaPartido"), "inicio": f.get("DataFiliacao"), "fim": f.get("DataDesfiliacao")} for f in fil]


def fetch_senado(doc, dry_run: bool):
    atuais = get_json(f"{SENADO_BASE}/senador/lista/atual.json") or {}
    parl = (((atuais.get("ListaParlamentarEmExercicio") or {}).get("Parlamentares") or {}).get("Parlamentar")) or []
    por_nome = {slug(p["IdentificacaoParlamentar"]["NomeParlamentar"]): p["IdentificacaoParlamentar"]["CodigoParlamentar"] for p in parl}
    itens = json.loads(VOT_PATH.read_text(encoding="utf-8"))["senado"]
    for c in doc["candidatos"]:
        if not any("senador" in (m.get("cargo") or "").lower() for m in c.get("mandatos", [])) and not c.get("senado_id"):
            continue
        cod = c.get("senado_id") or por_nome.get(slug(c["nome_urna"]))
        if not cod:
            print(f"  {c['nome_urna']}: não está em exercício; informe 'senado_id' no JSON", file=sys.stderr)
            continue
        c["senado_id"] = cod
        data = get_json(f"{SENADO_BASE}/senador/{cod}/autorias.json") or {}
        autorias = (((data.get("MateriasAutoriaParlamentar") or {}).get("Parlamentar") or {}).get("Autorias") or {}).get("Autoria") or []
        situacoes = {}
        for a in autorias:
            m = a.get("Materia") or {}
            if m.get("SiglaSubtipoMateria") in ("PL", "PLS", "PLP", "PEC", "PLC"):
                situacoes[m.get("CodigoMateria")] = get_json(f"{SENADO_BASE}/materia/situacaoatual/{m.get('CodigoMateria')}.json") or {}
                time.sleep(0.12)
        c["projetos"] = {"fonte": f"Senado Federal, dados abertos (parlamentar {cod})", "atualizado_em": HOJE, **normalizar_senado_autorias(autorias, situacoes)}
        rel = get_json(f"{SENADO_BASE}/senador/{cod}/relatorias.json") or {}
        rels = (((rel.get("MateriasRelatoriaParlamentar") or {}).get("Parlamentar") or {}).get("Relatorias") or {}).get("Relatoria") or []
        auto_rel = normalizar_senado_relatorias(rels)
        manuais = [r for r in c.get("relatorias", []) if not re.match(r"^(PL|PLS|PLP|PEC|PLC|MPV) ", r.get("titulo", ""))]
        c["relatorias"] = manuais + auto_rel
        fil = get_json(f"{SENADO_BASE}/senador/{cod}/filiacoes.json") or {}
        fils = (((fil.get("FiliacaoParlamentar") or {}).get("Parlamentar") or {}).get("Filiacoes") or {}).get("Filiacao") or []
        c["filiacoes"] = normalizar_senado_filiacoes(fils)
        vot = get_json(f"{SENADO_BASE}/senador/{cod}/votacoes.json") or {}
        vots = (((vot.get("VotacaoParlamentar") or {}).get("Parlamentar") or {}).get("Votacoes") or {}).get("Votacao") or []
        chaves = []
        for it in itens:
            for v in vots:
                m = v.get("Materia") or {}
                if m.get("SiglaSubtipoMateria") == it["tipo"] and str(m.get("NumeroMateria")) == str(it["numero"]) and str(m.get("AnoMateria")) == str(it["ano"]):
                    chaves.append({"tema": it["tema"], "quando": it["quando"], "data": (v.get("SessaoPlenaria") or {}).get("DataSessao"), "descricao": v.get("DescricaoVotacao"), "voto": v.get("DescricaoVoto")})
        c["votacoes_chave"] = chaves
        print(f"  {c['nome_urna']}: {c['projetos']['apresentados']['total']} matérias, {len(auto_rel)} relatorias, {len(chaves)} votos-chave")
    salvar(doc, dry_run)


# ============================================================ Portal da Transparência: emendas

def normalizar_emendas(rows: list) -> dict:
    total = 0.0
    por_destino = {}
    por_ano = {}
    for r in rows:
        v = brl(r.get("valorEmpenhado") or r.get("valorPago") or 0)
        total += v
        dest = r.get("localidadeDoGasto") or r.get("nomeMunicipio") or r.get("funcao") or "não informado"
        por_destino[dest] = por_destino.get(dest, 0.0) + v
        ano = str(r.get("ano") or "")
        por_ano[ano] = por_ano.get(ano, 0.0) + v
    top = sorted(por_destino.items(), key=lambda kv: -kv[1])[:10]
    return {"total_empenhado": round(total, 2), "por_ano": {k: round(v, 2) for k, v in sorted(por_ano.items())},
            "maiores_destinos": [{"destino": k, "valor": round(v, 2)} for k, v in top], "fonte": "Portal da Transparência (emendas)", "atualizado_em": HOJE}


def fetch_emendas(doc, dry_run: bool):
    key = os.environ.get("PORTAL_TRANSPARENCIA_KEY")
    if not key:
        print("  defina PORTAL_TRANSPARENCIA_KEY (cadastro gratuito no Portal da Transparência)", file=sys.stderr)
        return
    for c in doc["candidatos"]:
        if not (c.get("camara_id") or c.get("senado_id")):
            continue
        nome = c.get("nome_completo") or c["nome_urna"]
        rows, pagina = [], 1
        while True:
            data = get_json(f"{PORTAL_BASE}/emendas?nomeAutor={urllib.parse.quote(nome)}&pagina={pagina}", headers={"chave-api-dados": key})
            if not data:
                break
            rows.extend(data)
            if len(data) < 15:
                break
            pagina += 1
            time.sleep(0.4)
        if rows:
            c["emendas"] = normalizar_emendas(rows)
            print(f"  {c['nome_urna']}: R$ {c['emendas']['total_empenhado']:,.0f} em emendas")
    salvar(doc, dry_run)


# ============================================================ links de conferência (sem rede)

def gerar_links(c: dict) -> list:
    links = []
    if c.get("tse_url"):
        links.append({"nome": "TSE DivulgaCand (bens, certidões, contas)", "url": c["tse_url"]})
    else:
        links.append({"nome": "TSE DivulgaCand (busque o nome)", "url": "https://divulgacandcontas.tse.jus.br/divulga/#/"})
    if c.get("camara_id"):
        links.append({"nome": "Câmara: página do deputado", "url": f"https://www.camara.leg.br/deputados/{c['camara_id']}"})
        links.append({"nome": "Radar do Congresso", "url": f"https://radar.congressoemfoco.com.br/parlamentar/1{c['camara_id']}"})
        links.append({"nome": "Comovotou.org", "url": f"https://comovotou.org/deputado/{slug(sem_titulo(c['nome_urna']))}"})
    if c.get("senado_id"):
        links.append({"nome": "Senado: página do senador", "url": f"https://www25.senado.leg.br/web/senadores/senador/-/perfil/{c['senado_id']}"})
        links.append({"nome": "Radar do Congresso", "url": f"https://radar.congressoemfoco.com.br/parlamentar/2{c['senado_id']}"})
    if c["cargo"] == "deputado_estadual" or any("estadual" in (m.get("cargo") or "").lower() for m in c.get("mandatos", [])):
        links.append({"nome": "Ales: deputados", "url": "https://www.al.es.gov.br/Deputado/Lista"})
    if any(("prefeit" in (m.get("cargo") or "").lower()) for m in c.get("mandatos", [])):
        links.append({"nome": "TCE-ES: consulta de processos (contas de prefeito)", "url": "https://www.tcees.tc.br/consultas/"})
    links.append({"nome": "Jusbrasil (processos pelo nome)", "url": "https://www.jusbrasil.com.br/busca?q=" + urllib.parse.quote(c.get("nome_completo") or c["nome_urna"])})
    return links


def fetch_links(doc, dry_run: bool):
    for c in doc["candidatos"]:
        c["links"] = gerar_links(c)
    print(f"  links gerados para {len(doc['candidatos'])} candidatos")
    salvar(doc, dry_run)


# ============================================================ main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for f in ("tse", "contas", "camara", "senado", "emendas", "links", "tudo"):
        ap.add_argument(f"--{f}", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="não grava o JSON")
    a = ap.parse_args()
    if not any([a.tse, a.contas, a.camara, a.senado, a.emendas, a.links, a.tudo]):
        ap.error("escolha ao menos uma fonte (ou --tudo)")
    doc = carregar()
    passos = [("TSE", a.tse or a.tudo, fetch_tse), ("Contas de campanha", a.contas or a.tudo, fetch_contas),
              ("Câmara", a.camara or a.tudo, fetch_camara), ("Senado", a.senado or a.tudo, fetch_senado),
              ("Emendas", a.emendas or a.tudo, fetch_emendas), ("Links", a.links or a.tudo, fetch_links)]
    for nome, ligado, fn in passos:
        if ligado:
            print(f"== {nome}")
            fn(doc, a.dry_run)
    print("agora rode: python3 scripts/build_bundle.py")


if __name__ == "__main__":
    main()
