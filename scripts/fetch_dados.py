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
  --sancoes   CPF do candidato x lista do TCU (contas irregulares, CSV local em
              data/cache/tcu_contas_irregulares*.csv), CEIS/CNEP/CEAF e servidores
              federais do Portal da Transparência (precisa da chave em chaves.env).
  --noticias  últimas manchetes do Google Notícias por candidato (RSS, sem chave, ~15 min).
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

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
import _chaves  # noqa: E402,F401  (lê chaves.env: PORTAL_TRANSPARENCIA_KEY)
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
            if exc.code in (400, 404, 422):
                # erro de pedido: repetir não ajuda
                if os.environ.get("DEBUG"):
                    print(f"  HTTP {exc.code}: {url}", file=sys.stderr)
                return None
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


SIGLAS = {"AVANTE": "Avante", "PODE": "Podemos", "PODEMOS": "Podemos", "REPUBLICANOS": "Republicanos", "UNIÃO": "União", "UNIAO": "União",
          "NOVO": "Novo", "SOLIDARIEDADE": "Solidariedade", "CIDADANIA": "Cidadania", "REDE": "Rede", "MISSÃO": "Missão", "MISSAO": "Missão",
          "DEMOCRATA": "Democrata", "MOBILIZA": "Mobiliza", "PC DO B": "PCdoB", "PCDOB": "PCdoB", "AGIR": "Agir", "PATRIOTA": "Patriota", "PROS": "PROS"}
CONECTIVOS = {"da", "de", "do", "das", "dos", "e", "o", "a", "os", "as", "d'", "di", "del", "von", "van"}


def normalizar_sigla(sg) -> str | None:
    if not sg:
        return None
    t = str(sg).strip()
    return SIGLAS.get(t.upper(), t)


def titulo_pt(txt: str) -> str:
    """Capitaliza nome mantendo conectivos em minúsculas: 'GILVAN O FEDERAL DA DIREITA' -> 'Gilvan o Federal da Direita'."""
    if not txt:
        return ""
    if txt != txt.upper():
        return txt.strip()
    partes = txt.strip().lower().split()
    out = []
    for i, w in enumerate(partes):
        out.append(w if (w in CONECTIVOS and i > 0) else w.capitalize())
    return " ".join(out)


def slug(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", str(txt or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", txt.lower()).strip("-")


def sem_titulo(nome: str) -> str:
    return re.sub(r"^(dr\.?|dra\.?|prof\.?|professora?|delegad[oa]|capit[aã]o|coronel|cabo|sargento|pastor|bispo|engenheiro)\s+", "", nome, flags=re.I)


def carregar():
    doc = json.loads(CAND_PATH.read_text(encoding="utf-8"))
    for c in doc["candidatos"]:
        c["partido"] = normalizar_sigla(c.get("partido"))
        c["nome_urna"] = titulo_pt(c.get("nome_urna") or "")
    return doc


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


# O TSE escreve isso quando o campo não se aplica ou não foi informado.
MARCADORES_VAZIO_TSE = {"#NULO#", "#NULO", "#NE#", "#NE", "-1", "-4", "NÃO INFORMADO", "NAO INFORMADO", "NÃO DIVULGÁVEL", "NAO DIVULGAVEL"}


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
                    yield {k: ("" if (v or "").strip().upper() in MARCADORES_VAZIO_TSE else v) for k, v in row.items()}


def normalizar_csv_candidato(row: dict) -> dict | None:
    """Uma linha de consulta_cand_2026_XX.csv -> campos da ficha. None se não for cargo titular."""
    cargo = CD_CARGO.get(str(row.get("CD_CARGO", "")).strip())
    if not cargo:
        return None
    detalhe = (row.get("DS_DETALHE_SITUACAO_CAND") or row.get("DS_SITUACAO_CANDIDATURA") or "")
    idade = row.get("NR_IDADE_DATA_POSSE")
    return {
        "cargo": cargo,
        "nome_urna": titulo_pt(row.get("NM_URNA_CANDIDATO") or ""),
        "nome_completo": titulo_pt(row.get("NM_CANDIDATO") or ""),
        "numero": (row.get("NR_CANDIDATO") or "").strip() or None,
        "partido": normalizar_sigla(row.get("SG_PARTIDO")),
        "situacao": mapear_situacao(detalhe),
        "situacao_detalhe": detalhe.strip().capitalize() or None,
        "idade": int(idade) if idade and idade.strip().isdigit() and int(idade) > 0 else None,
        "ocupacao": (row.get("DS_OCUPACAO") or "").strip().capitalize() or None,
        "escolaridade": (row.get("DS_GRAU_INSTRUCAO") or "").strip().capitalize() or None,
        "cpf": re.sub(r"\D", "", row.get("NR_CPF_CANDIDATO") or "") or None,
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


def linhas_contas(zip_path: pathlib.Path, base: str):
    """Linhas do CSV estadual (_ES) mais as do nacional (_BRASIL, que tem o país todo) só com SG_UF=BR.

    Sem esse filtro os candidatos do ES seriam contados duas vezes; sem o nacional,
    os presidenciáveis ficariam de fora.
    """
    yield from ler_csv_zip(zip_path, (f"{base}_2026_ES.csv",))
    for r in ler_csv_zip(zip_path, (f"{base}_2026_BRASIL.csv", f"{base}_2026_BR.csv")):
        if (r.get("SG_UF") or "").strip().upper() == "BR":
            yield r


def normalizar_csv_despesas(contratadas, pagas) -> dict:
    """Linhas de despesas_contratadas_candidatos e despesas_pagas_candidatos -> {SQ_CANDIDATO: {...}}

    O arquivo de pagas não tem SQ_CANDIDATO, só SQ_PRESTADOR_CONTAS; o de contratadas
    tem os dois e serve de tradução.
    """
    por = {}
    prestador_para_cand = {}
    for r in contratadas:
        sq = (r.get("SQ_CANDIDATO") or "").strip()
        if not sq:
            continue
        prest = (r.get("SQ_PRESTADOR_CONTAS") or "").strip()
        if prest:
            prestador_para_cand[prest] = sq
        v = brl(r.get("VR_DESPESA_CONTRATADA") or r.get("VR_DESPESA"))
        forn = (r.get("NM_FORNECEDOR") or r.get("NM_FORNECEDOR_RFB") or "não identificado").strip()
        tipo = (r.get("DS_ORIGEM_DESPESA") or r.get("DS_DESPESA") or "outros").strip().capitalize()
        c = por.setdefault(sq, {"despesas": 0.0, "despesas_pagas": None, "_forn": {}, "_tipo": {}})
        c["despesas"] += v
        c["_forn"][forn] = c["_forn"].get(forn, 0.0) + v
        c["_tipo"][tipo] = c["_tipo"].get(tipo, 0.0) + v
    for r in pagas:
        sq = (r.get("SQ_CANDIDATO") or "").strip() or prestador_para_cand.get((r.get("SQ_PRESTADOR_CONTAS") or "").strip(), "")
        if not sq:
            continue
        v = brl(r.get("VR_PAGTO_DESPESA") or r.get("VR_PAGAMENTO") or r.get("VR_DESPESA"))
        c = por.setdefault(sq, {"despesas": 0.0, "despesas_pagas": None, "_forn": {}, "_tipo": {}})
        c["despesas_pagas"] = (c["despesas_pagas"] or 0.0) + v
    for c in por.values():
        c["despesas"] = round(c["despesas"], 2)
        if c["despesas_pagas"] is not None:
            c["despesas_pagas"] = round(c["despesas_pagas"], 2)
        c["maiores_fornecedores"] = [{"nome": k, "valor": round(v, 2)} for k, v in sorted(c.pop("_forn").items(), key=lambda kv: -kv[1])[:10]]
        c["despesas_por_tipo"] = [{"tipo": k, "valor": round(v, 2)} for k, v in sorted(c.pop("_tipo").items(), key=lambda kv: -kv[1])[:6]]
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
        item = {"ano": ano, "cargo": titulo_pt(limpo(r.get("DS_CARGO")) or ""), "partido": normalizar_sigla(limpo(r.get("SG_PARTIDO"))),
                "uf": titulo_pt(limpo(r.get("NM_UE")) or ""), "resultado": limpo(r.get("DS_SIT_TOT_TURNO")), "turno": limpo(r.get("NR_TURNO")),
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
            for k in ("numero", "situacao", "situacao_detalhe", "tse_id", "tse_url", "idade", "ocupacao", "escolaridade", "cpf"):
                if n.get(k) and (k in ("situacao", "situacao_detalhe", "tse_id", "tse_url", "cpf", "escolaridade") or not alvo.get(k)):
                    alvo[k] = n[k]
            if b:
                alvo["bens"] = b
            atualizados += 1
        else:
            doc["candidatos"].append({
                "id": slug(n["nome_urna"]) + ("-" + n["numero"] if n["numero"] else ""), "cargo": n["cargo"], "nome_urna": n["nome_urna"],
                "nome_completo": n["nome_completo"], "partido": n["partido"], "numero": n["numero"], "idade": n["idade"], "ocupacao": n["ocupacao"],
                "escolaridade": n["escolaridade"], "cpf": n["cpf"],
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
    fundir_orfaos(doc)
    _atualizar_cobertura(doc)
    salvar(doc, dry_run)


AUTO_CAMPOS = ("tse_id", "tse_url", "numero", "situacao", "bens", "certidoes", "certidoes_arquivos", "proposta_governo_arquivos", "eleicoes_anteriores",
               "trocas_de_partido", "vezes_eleito", "campanha", "redes", "tse_complementar", "motivos_registro", "gastos", "comissoes", "votacoes_chave",
               "filiacoes", "emendas", "camara_id", "senado_id", "idade", "ocupacao", "foto", "reeleicao", "escolaridade", "cpf", "sancoes",
               "servidor_federal", "noticias")
PALAVRAS_FRACAS = {"dr", "dra", "prof", "professor", "professora", "delegado", "delegada", "capitao", "coronel", "cabo", "sargento", "pastor", "bispo",
                   "engenheiro", "escritor", "da", "de", "do", "das", "dos", "e", "o", "a", "junior", "filho", "neto", "santos", "silva", "souza", "oliveira", "federal", "direita"}


def _tokens(*textos):
    out = set()
    for t in textos:
        for w in slug(t or "").split("-"):
            if len(w) >= 4 and w not in PALAVRAS_FRACAS:
                out.add(w)
    return out


def fundir_orfaos(doc):
    """Casa fichas escritas à mão (sem tse_id) com fichas importadas do TSE cujo nome de urna é diferente.
    Regra: mesmo cargo, ao menos um sobrenome/apelido distintivo em comum, e só uma candidata possível."""
    importadas = [c for c in doc["candidatos"] if c.get("tse_id") and (c.get("resumo") or "").startswith("Importado do TSE")]
    orfaos = [c for c in doc["candidatos"] if not c.get("tse_id")]
    removidos = []
    for o in orfaos:
        tk = _tokens(o["nome_urna"], o.get("nome_completo"))
        cands = [i for i in importadas if i["cargo"] == o["cargo"] and tk & _tokens(i["nome_urna"], i.get("nome_completo"))]
        if len(cands) != 1:
            if cands:
                print(f"  {o['nome_urna']}: ambíguo entre {[c['nome_urna'] for c in cands]}; preencha 'tse_id' à mão")
            else:
                print(f"  {o['nome_urna']}: não achei correspondente no TSE (pode ter saído da disputa ou o nome mudou)")
            continue
        i = cands[0]
        for k, v in i.items():
            if k in AUTO_CAMPOS or k not in o or o.get(k) in (None, "", [], {}):
                if k == "situacao" and o.get("situacao_obs") and v != o.get("situacao"):
                    o["situacao_obs"] = f"TSE registra '{v}'. " + o["situacao_obs"]
                o[k] = v
        # projetos vindos da API são mais completos que a lista manual
        if i.get("projetos") and "API" in (i["projetos"].get("fonte") or ""):
            o["projetos"] = i["projetos"]
        if i.get("nome_urna") != o["nome_urna"]:
            o["nome_urna_tse"] = i["nome_urna"]
        removidos.append(i["id"])
        importadas.remove(i)
        print(f"  fundido: '{o['nome_urna']}' <- '{i['nome_urna']}' ({i['tse_id']})")
    doc["candidatos"] = [c for c in doc["candidatos"] if c["id"] not in removidos]
    print(f"  {len(removidos)} duplicatas removidas")


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
    por = normalizar_csv_receitas(linhas_contas(z, "receitas_candidatos"))
    desp = normalizar_csv_despesas(linhas_contas(z, "despesas_contratadas_candidatos"),
                                   linhas_contas(z, "despesas_pagas_candidatos"))
    n = nd = 0
    for c in doc["candidatos"]:
        sq = str(c.get("tse_id") or "")
        camp = por.get(sq)
        d = desp.get(sq)
        if not camp and not d:
            continue
        camp = camp or {"receitas": 0.0, "despesas": None, "fundo_publico_e_partido": 0.0, "maiores_doadores": [],
                        "fonte": "TSE Dados Abertos (prestação de contas 2026)", "atualizado_em": HOJE}
        if d:
            camp.update(d)
            nd += 1
        c["campanha"] = camp
        n += 1
    print(f"  contas preenchidas para {n} candidatos ({nd} com despesas)")
    if not nd:
        print("  aviso: nenhum CSV despesas_contratadas_candidatos_2026_*.csv no zip; o TSE atualiza esse arquivo separadamente")
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
    tentativas = [(c.get("nome_completo"), ""), (c["nome_urna"], "&siglaUf=ES"), (sem_titulo(c["nome_urna"]), "&siglaUf=ES"), (sem_titulo(c["nome_urna"]), "")]
    for nome, uf in tentativas:
        if not nome:
            continue
        data = get_json(f"{CAMARA_BASE}/deputados?nome={urllib.parse.quote(nome)}{uf}&ordem=ASC&ordenarPor=nome")
        dados = (data or {}).get("dados") or []
        if not dados:
            continue
        es = [d for d in dados if d.get("siglaUf") == "ES"]
        return (es or dados)[0]["id"]
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

TIPOS_LEI = ("PL", "PLS", "PLP", "PEC", "PLC", "MPV")


def ident_materia(m: dict) -> tuple:
    """Devolve (sigla, numero, ano, 'SIGLA N/ANO') a partir de qualquer versão do JSON do Senado."""
    m = m or {}
    if m.get("SiglaSubtipoMateria"):
        sg, nr, ano = m.get("SiglaSubtipoMateria"), str(m.get("NumeroMateria") or ""), str(m.get("AnoMateria") or "")
        return sg, nr, ano, f"{sg} {nr}/{ano}"
    ident = m.get("DescricaoIdentificacao") or m.get("Identificacao") or ""
    mm = re.match(r"^\s*([A-Z]+)\s+(\d+)\s*/\s*(\d{4})", ident)
    if mm:
        return mm.group(1), mm.group(2), mm.group(3), f"{mm.group(1)} {mm.group(2)}/{mm.group(3)}"
    return None, None, None, ident


def ementa_materia(m: dict) -> str:
    m = m or {}
    return (m.get("Ementa") or m.get("DescricaoEmenta") or m.get("EmentaMateria") or m.get("DescricaoIdentificacao") or "")[:240]


def normalizar_senado_autorias(autorias: list, situacoes: dict) -> dict:
    aprovados, tramitando, total = [], [], 0
    for a in autorias:
        m = a.get("Materia") or {}
        sg, nr, ano, ident = ident_materia(m)
        if sg not in TIPOS_LEI:
            continue
        total += 1
        desc = json.dumps(situacoes.get(m.get("Codigo") or m.get("CodigoMateria"), {}), ensure_ascii=False).lower()
        item = {"id": ident, "titulo": ementa_materia(m)}
        if "norma" in desc and ("transformad" in desc or "promulgad" in desc):
            item.update({"norma": "transformado em norma", "ano": ano, "status": "em vigor", "papel": "autor"})
            aprovados.append(item)
        elif "arquivad" in desc or "prejudicad" in desc or "rejeitad" in desc:
            continue
        else:
            if not desc or desc == "{}":
                item["obs"] = "situação não obtida"
            tramitando.append(item)
    return {"apresentados": {"total": total, "obs": "Só PL, PLS, PLP, PEC e MPV de autoria."}, "em_tramitacao": tramitando, "aprovados": aprovados}


def normalizar_senado_relatorias(rels: list) -> list:
    out = []
    for r in rels:
        m = r.get("Materia") or {}
        sg, nr, ano, ident = ident_materia(m)
        if sg not in TIPOS_LEI:
            continue
        com = r.get("Comissao") or {}
        sigla_com = com.get("SiglaComissao") or com.get("Sigla") or ""
        out.append({"titulo": f"{ident}: {ementa_materia(m)[:160]}",
                    "resultado": (r.get("DescricaoTipoRelator") or "relator") + (f" · {sigla_com}" if sigla_com else "") + (f" · designado em {r['DataDesignacao'][:10]}" if r.get("DataDesignacao") else ""),
                    "ano": ano})
    return out


def normalizar_senado_votacoes(vots: list, itens: list) -> list:
    chaves = []
    for it in itens:
        for v in vots:
            sg, nr, ano, ident = ident_materia(v.get("Materia") or {})
            if sg == it["tipo"] and str(nr) == str(it["numero"]) and str(ano) == str(it["ano"]):
                sess = v.get("SessaoPlenaria") or {}
                chaves.append({"tema": it["tema"], "quando": it["quando"], "data": sess.get("DataSessao") or sess.get("Data"),
                               "descricao": v.get("DescricaoVotacao") or v.get("Descricao") or ident,
                               "voto": v.get("DescricaoVoto") or v.get("SiglaDescricaoVoto") or v.get("Voto")})
    return chaves


def normalizar_senado_filiacoes(fil: list) -> list:
    return [{"partido": (f.get("Partido") or {}).get("SiglaPartido"), "inicio": f.get("DataFiliacao"), "fim": f.get("DataDesfiliacao")} for f in fil]


def _senadores_por_nome():
    por_nome = {}
    fontes = [f"{SENADO_BASE}/senador/lista/atual.json"] + [f"{SENADO_BASE}/senador/lista/legislatura/{n}/{n}.json" for n in (57, 56, 55, 54, 53)]
    for url in fontes:
        data = get_json(url) or {}
        raiz = data.get("ListaParlamentarEmExercicio") or data.get("ListaParlamentarLegislatura") or {}
        parl = ((raiz.get("Parlamentares") or {}).get("Parlamentar")) or []
        for p in parl:
            ident = p.get("IdentificacaoParlamentar") or {}
            for nome in (ident.get("NomeParlamentar"), ident.get("NomeCompletoParlamentar")):
                if nome and slug(nome) not in por_nome:
                    por_nome[slug(nome)] = ident.get("CodigoParlamentar")
    return por_nome


def _debug(rotulo, data):
    if os.environ.get("DEBUG"):
        txt = json.dumps(data, ensure_ascii=False)
        print(f"  [debug] {rotulo}: {txt[:700]}")


def fetch_senado(doc, dry_run: bool):
    por_nome = _senadores_por_nome()
    itens = json.loads(VOT_PATH.read_text(encoding="utf-8"))["senado"]
    for c in doc["candidatos"]:
        if not any("senador" in (m.get("cargo") or "").lower() for m in c.get("mandatos", [])) and not c.get("senado_id"):
            continue
        cod = c.get("senado_id") or por_nome.get(slug(c["nome_urna"])) or por_nome.get(slug(c.get("nome_completo") or ""))
        if not cod:
            print(f"  {c['nome_urna']}: não está em exercício; informe 'senado_id' no JSON", file=sys.stderr)
            continue
        c["senado_id"] = cod
        data = get_json(f"{SENADO_BASE}/senador/{cod}/autorias.json") or {}
        _debug(f"autorias {cod}", data)
        autorias = (((data.get("MateriasAutoriaParlamentar") or {}).get("Parlamentar") or {}).get("Autorias") or {}).get("Autoria") or []
        situacoes = {}
        for a in autorias:
            m = a.get("Materia") or {}
            sg, nr, ano, ident = ident_materia(m)
            cod_m = m.get("Codigo") or m.get("CodigoMateria")
            if sg in TIPOS_LEI and cod_m:
                situacoes[cod_m] = get_json(f"{SENADO_BASE}/materia/situacaoatual/{cod_m}.json") or {}
                time.sleep(0.12)
        c["projetos"] = {"fonte": f"Senado Federal, dados abertos (parlamentar {cod})", "atualizado_em": HOJE, **normalizar_senado_autorias(autorias, situacoes)}
        rel = get_json(f"{SENADO_BASE}/senador/{cod}/relatorias.json") or {}
        _debug(f"relatorias {cod}", rel)
        rels = (((rel.get("MateriasRelatoriaParlamentar") or {}).get("Parlamentar") or {}).get("Relatorias") or {}).get("Relatoria") or []
        auto_rel = normalizar_senado_relatorias(rels)
        manuais = [r for r in c.get("relatorias", []) if not re.match(r"^(PL|PLS|PLP|PEC|PLC|MPV) ", r.get("titulo", ""))]
        c["relatorias"] = manuais + auto_rel
        fil = get_json(f"{SENADO_BASE}/senador/{cod}/filiacoes.json") or {}
        _debug(f"filiacoes {cod}", fil)
        fils = (((fil.get("FiliacaoParlamentar") or {}).get("Parlamentar") or {}).get("Filiacoes") or {}).get("Filiacao") or []
        c["filiacoes"] = normalizar_senado_filiacoes(fils)
        vot = get_json(f"{SENADO_BASE}/senador/{cod}/votacoes.json") or {}
        _debug(f"votacoes {cod}", vot)
        vots = (((vot.get("VotacaoParlamentar") or {}).get("Parlamentar") or {}).get("Votacoes") or {}).get("Votacao") or []
        if vots and os.environ.get("DEBUG"):
            _debug("primeira votação", vots[0])
        if autorias and os.environ.get("DEBUG"):
            _debug("primeira autoria", autorias[0])
        c["votacoes_chave"] = normalizar_senado_votacoes(vots, itens)
        print(f"  {c['nome_urna']}: {c['projetos']['apresentados']['total']} matérias, {len(auto_rel)} relatorias, {len(c['votacoes_chave'])} votos-chave, {len(c['filiacoes'])} filiações")
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


# ============================================================ listas de sanção (TCU, Portal da Transparência)

def _so_digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def cpf_bate(cpf: str | None, mascarado) -> bool:
    """Compara um CPF completo com um valor que pode vir mascarado (***.123.456-**) ou completo."""
    if not cpf:
        return False
    m = str(mascarado or "")
    d = _so_digitos(m)
    if len(d) == 11:
        return d == cpf
    # mascarado: sobram os 6 do meio
    meio = re.sub(r"\D", "", m.replace("*", ""))
    return len(meio) >= 6 and cpf[3:9] == meio[:6]


def _nome_normal(n: str) -> str:
    import unicodedata
    n = "".join(ch for ch in unicodedata.normalize("NFD", n or "") if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", n).strip().upper()


def carregar_tcu() -> list[dict]:
    """Lê data/cache/tcu_contas_irregulares*.csv (baixado à mão do TCU). Aceita qualquer cabeçalho com CPF e NOME."""
    import csv
    linhas = []
    for arq in sorted(CACHE.glob("tcu_contas_irregulares*.csv")):
        raw = arq.read_bytes()
        texto = raw.decode("utf-8-sig") if b"\xef\xbb\xbf" in raw[:3] or b"\xc3" in raw[:2000] else raw.decode("latin-1")
        dialeto = ";" if texto.count(";") > texto.count(",") else ","
        for r in csv.DictReader(io.StringIO(texto), delimiter=dialeto):
            col_cpf = next((k for k in r if k and "CPF" in k.upper()), None)
            col_nome = next((k for k in r if k and "NOME" in k.upper()), None)
            if not (col_cpf and col_nome):
                continue
            linhas.append({"cpf": r.get(col_cpf), "nome": r.get(col_nome), "linha": {k: v for k, v in r.items() if k}})
    return linhas


def fetch_sancoes(doc, dry_run: bool):
    """Cruza cada candidato (por CPF) com: lista do TCU de contas irregulares (CSV local) e, com a chave do
    Portal da Transparência, CEIS, CNEP e CEAF (sanções a empresas, pessoas e servidores) e cadastro de
    servidores federais."""
    tcu = carregar_tcu()
    if tcu:
        print(f"  TCU: {len(tcu)} responsáveis na lista local")
    else:
        print("  TCU: nenhum data/cache/tcu_contas_irregulares*.csv; baixe a 'lista de responsáveis com contas julgadas irregulares' em portal.tcu.gov.br e salve com esse nome")
    key = os.environ.get("PORTAL_TRANSPARENCIA_KEY")
    if not key:
        print("  Portal da Transparência: sem PORTAL_TRANSPARENCIA_KEY em chaves.env; pulando CEIS/CNEP/CEAF e servidores")
    h = {"chave-api-dados": key} if key else None
    sem_cpf = 0
    achados = 0
    respostas = {"ceis": 0, "cnep": 0, "ceaf": 0, "servidores": 0}
    servidores = 0
    total = len(doc["candidatos"])
    if key:
        print(f"  {total} candidatos x 4 consultas com pausa de 0,7 s: uns {total * 4 * 0.75 / 60:.0f} minutos. Só imprime quando acha algo.")
    inicio = time.time()
    for i, c in enumerate(doc["candidatos"], 1):
        if i % 10 == 0:
            dec = time.time() - inicio
            resta = dec / i * (total - i)
            print(f"  {i}/{total} consultados em {dec / 60:.1f} min, faltam ~{resta / 60:.0f} min ({achados} com sanção, {servidores} servidores)", flush=True)
        if i % 50 == 0:
            salvar(doc, dry_run)
        cpf = c.get("cpf")
        if not cpf:
            sem_cpf += 1
            continue
        nome = c.get("nome_completo") or c["nome_urna"]
        res = {"verificado_em": HOJE, "tcu": [], "ceis": [], "cnep": [], "ceaf": [], "fontes_consultadas": []}
        if tcu:
            res["fontes_consultadas"].append("TCU contas irregulares (lista local)")
            for t in tcu:
                if cpf_bate(cpf, t["cpf"]) or (_nome_normal(t["nome"]) == _nome_normal(nome) and not _so_digitos(t["cpf"])):
                    res["tcu"].append({k: v for k, v in t["linha"].items() if v and "CPF" not in k.upper()})
        if key:
            for lista, param in (("ceis", "nomeSancionado"), ("cnep", "nomeSancionado"), ("ceaf", "nomeSancionado")):
                data = get_json(f"{PORTAL_BASE}/{lista}?{param}={urllib.parse.quote(nome)}&pagina=1", headers=h)
                if data is not None:
                    respostas[lista] += 1
                res["fontes_consultadas"].append(f"Portal da Transparência {lista.upper()}")
                for item in data or []:
                    pessoa = item.get("pessoa") or item.get("sancionado") or item.get("servidor") or {}
                    cpf_item = pessoa.get("cpfFormatado") or pessoa.get("cpf") or item.get("cpfFormatado") or item.get("cpf")
                    nome_item = pessoa.get("nome") or item.get("nome") or item.get("nomeSancionado") or ""
                    if cpf_bate(cpf, cpf_item) or (not cpf_item and _nome_normal(nome_item) == _nome_normal(nome)):
                        res[lista].append({
                            "orgao": (item.get("orgaoSancionador") or {}).get("nome") or item.get("orgaoSancionador") or item.get("orgaoLotacao"),
                            "tipo": (item.get("tipoSancao") or {}).get("descricaoResumida") or item.get("tipoSancao") or item.get("tipoPunicao") or item.get("descricaoPunicao"),
                            "inicio": item.get("dataInicioSancao") or item.get("dataPublicacao") or item.get("dataPublicacaoPunicao"),
                            "fim": item.get("dataFimSancao"),
                            "fundamentacao": (item.get("fundamentacao") or [{}])[0].get("descricao") if isinstance(item.get("fundamentacao"), list) else item.get("fundamentacao"),
                        })
                time.sleep(0.7)
            # /servidores exige CPF (busca por nome devolve 400)
            serv = get_json(f"{PORTAL_BASE}/servidores?cpf={cpf}&pagina=1", headers=h)
            time.sleep(0.7)
            if serv is not None:
                respostas["servidores"] += 1
            vinculos = []
            if os.environ.get("DEBUG") and serv:
                print(f"  DEBUG servidores {c['nome_urna']}: {json.dumps(serv[0], ensure_ascii=False)[:600]}", file=sys.stderr)
            for item in serv or []:
                # a consulta já é por CPF: o que volta é o próprio candidato
                fv = item.get("fichaVinculo") or item
                vinculos.append({"orgao": (fv.get("orgaoServidorLotacao") or {}).get("nome") or fv.get("orgaoLotacao") or (item.get("orgaoServidorExercicio") or {}).get("nome"),
                                 "cargo": fv.get("cargo") or (item.get("cargo") or {}).get("descricao") or item.get("descricaoCargo"),
                                 "situacao": fv.get("situacaoVinculo") or item.get("situacao"),
                                 "tipo": (item.get("tipoServidor") or {}).get("descricao") or item.get("tipoVinculo")})
            if vinculos:
                servidores += 1
                c["servidor_federal"] = {"vinculos": vinculos[:5], "fonte": "Portal da Transparência (servidores)", "consultado_em": HOJE}
                print(f"  servidor federal: {c['nome_urna']} ({vinculos[0].get('cargo') or '?'} · {vinculos[0].get('orgao') or '?'})")
        hits = sum(len(res[k]) for k in ("tcu", "ceis", "cnep", "ceaf"))
        c["sancoes"] = res
        if hits:
            achados += 1
            print(f"  ATENÇÃO {c['nome_urna']}: " + ", ".join(f"{k} {len(res[k])}" for k in ("tcu", "ceis", "cnep", "ceaf") if res[k]))
    print(f"  sanções: {achados} candidatos com ocorrência; {servidores} servidores federais; {sem_cpf} sem CPF (rode --tse de novo para preencher)")
    if key:
        print("  respostas válidas do Portal por lista: " + ", ".join(f"{k} {v}" for k, v in respostas.items()) + "  (zero em alguma = endpoint ou parâmetro errado; rode com DEBUG=1)")
    salvar(doc, dry_run)


# ============================================================ notícias (Google Notícias, RSS)

NOTICIAS_URL = "https://news.google.com/rss/search?q={q}&hl=pt-BR&gl=BR&ceid=BR:pt-419"


def consulta_noticias(c: dict) -> str:
    nome = c["nome_urna"] if len(c["nome_urna"].split()) >= 2 else (c.get("nome_completo") or c["nome_urna"])
    if c["cargo"] == "presidente":
        return f'"{nome}" (candidato OR presidente OR eleição)'
    return f'"{nome}" ("Espírito Santo" OR ES OR capixaba OR candidato OR deputado OR senador OR governador)'


def ler_rss(xml_bytes: bytes) -> list[dict]:
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    itens = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return itens
    for it in root.iter("item"):
        titulo = (it.findtext("title") or "").strip()
        fonte = it.find("source")
        fonte_nome = (fonte.text or "").strip() if fonte is not None else ""
        if fonte_nome and titulo.endswith(" - " + fonte_nome):
            titulo = titulo[: -len(" - " + fonte_nome)].strip()
        data = None
        try:
            data = parsedate_to_datetime(it.findtext("pubDate") or "").date().isoformat()
        except Exception:  # noqa: BLE001
            pass
        itens.append({"titulo": titulo, "link": (it.findtext("link") or "").strip(), "data": data, "fonte": fonte_nome or None})
    return itens


def fetch_noticias(doc, dry_run: bool, limite: int = 8):
    """Últimas manchetes do Google Notícias para cada candidato. Não interpreta; só guarda título, fonte, data e link."""
    pasta = CACHE / "noticias"
    pasta.mkdir(parents=True, exist_ok=True)
    feitos = com = 0
    for c in doc["candidatos"]:
        if c.get("situacao") == "desistiu":
            continue
        q = consulta_noticias(c)
        cache = pasta / f"{c.get('tse_id') or c['id']}.xml"
        if cache.exists() and (time.time() - cache.stat().st_mtime) < 86400 * 3:
            xml_bytes = cache.read_bytes()
        else:
            url = NOTICIAS_URL.format(q=urllib.parse.quote(q))
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=60) as resp:
                    xml_bytes = resp.read()
            except Exception as exc:  # noqa: BLE001
                print(f"  falhou {c['nome_urna']}: {exc}", file=sys.stderr)
                time.sleep(3)
                continue
            cache.write_bytes(xml_bytes)
            time.sleep(1.2)
        itens = ler_rss(xml_bytes)
        itens = sorted(itens, key=lambda x: x["data"] or "", reverse=True)[:limite]
        c["noticias"] = {"consultado_em": HOJE, "busca": q, "itens": itens,
                         "fonte": "Google Notícias (RSS); pode incluir homônimos"}
        feitos += 1
        com += bool(itens)
        if feitos % 50 == 0:
            print(f"  {feitos} consultados ({com} com notícia)")
            salvar(doc, dry_run)
    print(f"  notícias: {feitos} candidatos consultados, {com} com pelo menos uma manchete")
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
    for f in ("tse", "contas", "camara", "senado", "emendas", "sancoes", "noticias", "links", "fundir", "tudo"):
        ap.add_argument(f"--{f}", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="não grava o JSON")
    a = ap.parse_args()
    if not any([a.tse, a.contas, a.camara, a.senado, a.emendas, a.sancoes, a.noticias, a.links, a.fundir, a.tudo]):
        ap.error("escolha ao menos uma fonte (ou --tudo)")
    doc = carregar()
    passos = [("TSE", a.tse or a.tudo, fetch_tse), ("Contas de campanha", a.contas or a.tudo, fetch_contas),
              ("Câmara", a.camara or a.tudo, fetch_camara), ("Senado", a.senado or a.tudo, fetch_senado),
              ("Emendas", a.emendas or a.tudo, fetch_emendas), ("Listas de sanção", a.sancoes or a.tudo, fetch_sancoes),
              ("Notícias", a.noticias or a.tudo, fetch_noticias),
              ("Fusão de duplicatas", a.fundir, lambda d, dr: (fundir_orfaos(d), salvar(d, dr))), ("Links", a.links or a.tudo, fetch_links)]
    for nome, ligado, fn in passos:
        if ligado:
            print(f"== {nome}")
            fn(doc, a.dry_run)
    print("agora rode: python3 scripts/build_bundle.py")


if __name__ == "__main__":
    main()
