#!/usr/bin/env python3
"""Coleta dados públicos e atualiza data/candidatos.json.

Este script precisa de internet aberta para os domínios do TSE, da Câmara e do
Senado. Ele NÃO foi executado no ambiente em que foi escrito (rede bloqueada),
então trate a primeira rodada como um teste: rode com --dry-run, confira o que
ele imprime e só depois deixe gravar.

Uso:
    python3 scripts/fetch_dados.py --tse                 # lista completa de candidatos do ES (e presidente)
    python3 scripts/fetch_dados.py --camara              # projetos dos candidatos que são/foram deputados federais
    python3 scripts/fetch_dados.py --senado              # projetos dos candidatos que são/foram senadores
    python3 scripts/fetch_dados.py --tse --camara --senado --dry-run

O que cada fonte dá:
- TSE (DivulgaCandContas): nome de urna, número, partido, situação do registro,
  vice/suplentes, foto. Preenche 'numero' e 'situacao' e cria entradas novas
  para quem ainda não está no JSON (com projetos = null).
- Câmara (dadosabertos.camara.leg.br): proposições de autoria (PL, PLP, PEC) e
  a situação de cada uma. Classifica em aprovadas (transformadas em norma),
  em tramitação e arquivadas.
- Senado (legis.senado.leg.br/dadosabertos): autorias e situação atual.
- Ales: não tem API pública estável. Fica manual.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAND_PATH = ROOT / "data" / "candidatos.json"

TSE_BASE = "https://divulgacandcontas.tse.jus.br/divulga/rest/v1"
CAMARA_BASE = "https://dadosabertos.camara.leg.br/api/v2"
SENADO_BASE = "https://legis.senado.leg.br/dadosabertos"

# códigos de cargo do DivulgaCand
CARGOS_TSE = {
    "presidente": (1, "BR"),
    "governador": (3, "ES"),
    "senador": (5, "ES"),
    "deputado_federal": (6, "ES"),
    "deputado_estadual": (7, "ES"),
}
UA = {"User-Agent": "estudo-candidatos-2026/1.0 (uso pessoal, ver README)", "Accept": "application/json"}


def get_json(url: str, tentativas: int = 3, pausa: float = 0.6):
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            if i == tentativas - 1:
                print(f"  falhou: {url} ({exc})", file=sys.stderr)
                return None
            time.sleep(pausa * (2 ** i))
    return None


def slug(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", txt.lower()).strip("-")


def carregar():
    return json.loads(CAND_PATH.read_text(encoding="utf-8"))


def salvar(doc, dry_run: bool):
    if dry_run:
        print("(dry-run) não gravei nada")
        return
    CAND_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"gravado: {CAND_PATH.relative_to(ROOT)}")


# ----------------------------------------------------------------------------- TSE

def id_eleicao_2026():
    data = get_json(f"{TSE_BASE}/eleicao/ordinarias") or []
    for e in data:
        if str(e.get("ano")) == "2026":
            return e["id"]
    raise SystemExit("não achei a eleição de 2026 em /eleicao/ordinarias")


def fetch_tse(doc, dry_run: bool):
    id_el = id_eleicao_2026()
    por_id = {c["id"]: c for c in doc["candidatos"]}
    novos = 0
    atualizados = 0
    for cargo, (cod, uf) in CARGOS_TSE.items():
        url = f"{TSE_BASE}/candidatura/listar/2026/{uf}/{id_el}/{cod}/candidatos"
        lista = get_json(url)
        if not lista or "candidatos" not in lista:
            print(f"  {cargo}: sem resposta", file=sys.stderr)
            continue
        for c in lista["candidatos"]:
            nome_urna = c.get("nomeUrna") or c.get("nomeCompleto")
            cid = slug(nome_urna)
            alvo = por_id.get(cid) or _achar_por_nome(doc["candidatos"], cargo, nome_urna)
            registro = {
                "numero": str(c.get("numero")) if c.get("numero") else None,
                "situacao": _mapear_situacao(c.get("descricaoSituacao") or c.get("descricaoTotalizacao") or ""),
                "partido": (c.get("partido") or {}).get("sigla") or alvo and alvo.get("partido"),
                "foto": c.get("fotoUrl"),
                "tse_id": c.get("id"),
            }
            if alvo:
                for k, v in registro.items():
                    if v and not alvo.get(k) or k in ("situacao", "tse_id", "foto"):
                        alvo[k] = v
                atualizados += 1
            else:
                doc["candidatos"].append({
                    "id": cid, "cargo": cargo, "nome_urna": nome_urna,
                    "nome_completo": c.get("nomeCompleto"), "partido": registro["partido"],
                    "numero": registro["numero"], "idade": None, "ocupacao": None,
                    "situacao": registro["situacao"], "tipo_historico": "sem_dados",
                    "inicio_politica": None, "resumo": "Importado do TSE; histórico ainda não pesquisado.",
                    "mandatos": [], "projetos": None, "foto": registro["foto"], "tse_id": registro["tse_id"],
                    "fontes": [f"https://divulgacandcontas.tse.jus.br/divulga/#/candidato/2026/{id_el}/{uf}/{c.get('id')}"],
                })
                novos += 1
        print(f"  {cargo}: {len(lista['candidatos'])} no TSE")
    doc["meta"]["atualizado_em_tse"] = time.strftime("%Y-%m-%d")
    print(f"TSE: {atualizados} atualizados, {novos} novos")
    salvar(doc, dry_run)


def _achar_por_nome(cands, cargo, nome_urna):
    alvo = slug(nome_urna)
    for c in cands:
        if c["cargo"] == cargo and slug(c["nome_urna"]) == alvo:
            return c
    return None


def _mapear_situacao(txt: str) -> str:
    t = txt.lower()
    if "indeferido" in t:
        return "indeferido"
    if "deferido" in t or "apto" in t:
        return "deferido"
    if "renúncia" in t or "renuncia" in t or "desist" in t:
        return "desistiu"
    return "aguardando"


# ---------------------------------------------------------------------------- Câmara

def fetch_camara(doc, dry_run: bool):
    """Para cada candidato com mandato de deputado federal, busca as proposições."""
    for c in doc["candidatos"]:
        if not any("deputad" in (m.get("cargo") or "").lower() and "federal" in (m.get("cargo") or "").lower() for m in c.get("mandatos", [])):
            continue
        dep_id = c.get("camara_id") or _camara_id_por_nome(c)
        if not dep_id:
            print(f"  {c['nome_urna']}: não achei na Câmara", file=sys.stderr)
            continue
        c["camara_id"] = dep_id
        props = _camara_proposicoes(dep_id)
        aprovados, tramitando, arquivados = [], [], 0
        for p in props:
            det = get_json(f"{CAMARA_BASE}/proposicoes/{p['id']}")
            if not det:
                continue
            st = det["dados"].get("statusProposicao", {})
            desc = (st.get("descricaoSituacao") or "").lower()
            item = {"id": f"{p['siglaTipo']} {p['numero']}/{p['ano']}", "titulo": (det["dados"].get("ementa") or "")[:240]}
            if "transformad" in desc and "norma" in desc:
                item.update({"norma": st.get("despacho") or "transformado em norma jurídica", "ano": p["ano"], "status": "em vigor", "papel": "autor"})
                aprovados.append(item)
            elif "arquivad" in desc:
                arquivados += 1
            else:
                item["obs"] = st.get("descricaoSituacao") or st.get("descricaoTramitacao")
                tramitando.append(item)
            time.sleep(0.15)
        c["projetos"] = {
            "fonte": f"Câmara dos Deputados, API dadosabertos (deputado {dep_id})",
            "atualizado_em": time.strftime("%Y-%m-%d"),
            "apresentados": {"total": len(props), "obs": f"{arquivados} arquivadas. Só PL, PLP e PEC de autoria própria."},
            "em_tramitacao": tramitando,
            "aprovados": aprovados,
        }
        print(f"  {c['nome_urna']}: {len(props)} proposições, {len(aprovados)} viraram lei, {len(tramitando)} tramitando")
    salvar(doc, dry_run)


def _camara_id_por_nome(c):
    nome = c.get("nome_completo") or c["nome_urna"]
    q = urllib.parse.quote(nome)
    data = get_json(f"{CAMARA_BASE}/deputados?nome={q}&siglaUf=ES&ordem=ASC&ordenarPor=nome")
    if data and data.get("dados"):
        return data["dados"][0]["id"]
    # tenta só o nome de urna sem título
    q = urllib.parse.quote(re.sub(r"^(dr\.?|dra\.?|prof\.?|professora?|delegad[oa]|capit[aã]o|coronel)\s+", "", c["nome_urna"], flags=re.I))
    data = get_json(f"{CAMARA_BASE}/deputados?nome={q}&siglaUf=ES")
    return data["dados"][0]["id"] if data and data.get("dados") else None


def _camara_proposicoes(dep_id):
    out, pagina = [], 1
    while True:
        url = f"{CAMARA_BASE}/proposicoes?idDeputadoAutor={dep_id}&siglaTipo=PL&siglaTipo=PLP&siglaTipo=PEC&itens=100&pagina={pagina}&ordem=ASC&ordenarPor=id"
        data = get_json(url)
        if not data or not data.get("dados"):
            break
        out.extend(data["dados"])
        if not any(l.get("rel") == "next" for l in data.get("links", [])):
            break
        pagina += 1
    return out


# ---------------------------------------------------------------------------- Senado

def fetch_senado(doc, dry_run: bool):
    atuais = get_json(f"{SENADO_BASE}/senador/lista/atual.json") or {}
    parlamentares = (((atuais.get("ListaParlamentarEmExercicio") or {}).get("Parlamentares") or {}).get("Parlamentar")) or []
    por_nome = {slug(p["IdentificacaoParlamentar"]["NomeParlamentar"]): p["IdentificacaoParlamentar"]["CodigoParlamentar"] for p in parlamentares}
    for c in doc["candidatos"]:
        if not any("senador" in (m.get("cargo") or "").lower() for m in c.get("mandatos", [])):
            continue
        cod = c.get("senado_id") or por_nome.get(slug(c["nome_urna"]))
        if not cod:
            print(f"  {c['nome_urna']}: não está em exercício no Senado; informe 'senado_id' manualmente no JSON", file=sys.stderr)
            continue
        c["senado_id"] = cod
        data = get_json(f"{SENADO_BASE}/senador/{cod}/autorias.json") or {}
        autorias = (((data.get("MateriasAutoriaParlamentar") or {}).get("Parlamentar") or {}).get("Autorias") or {}).get("Autoria") or []
        aprovados, tramitando, total = [], [], 0
        for a in autorias:
            m = a.get("Materia") or {}
            if m.get("SiglaSubtipoMateria") not in ("PL", "PLS", "PLP", "PEC", "PLC"):
                continue
            total += 1
            cod_m = m.get("CodigoMateria")
            sit = get_json(f"{SENADO_BASE}/materia/situacaoatual/{cod_m}.json") or {}
            desc = json.dumps(sit, ensure_ascii=False).lower()
            item = {"id": f"{m.get('SiglaSubtipoMateria')} {m.get('NumeroMateria')}/{m.get('AnoMateria')}", "titulo": (m.get('DescricaoIdentificacaoMateria') or m.get('Ementa') or '')[:240]}
            if "norma" in desc and ("transformad" in desc or "promulgad" in desc):
                item.update({"norma": "transformado em norma", "ano": m.get("AnoMateria"), "status": "em vigor", "papel": "autor"})
                aprovados.append(item)
            elif "arquivad" in desc:
                continue
            else:
                tramitando.append(item)
            time.sleep(0.15)
        c["projetos"] = {
            "fonte": f"Senado Federal, dados abertos (parlamentar {cod})",
            "atualizado_em": time.strftime("%Y-%m-%d"),
            "apresentados": {"total": total, "obs": "Só PL, PLS, PLP e PEC de autoria."},
            "em_tramitacao": tramitando, "aprovados": aprovados,
        }
        print(f"  {c['nome_urna']}: {total} matérias, {len(aprovados)} viraram norma")
    salvar(doc, dry_run)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tse", action="store_true")
    ap.add_argument("--camara", action="store_true")
    ap.add_argument("--senado", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="não grava o JSON")
    args = ap.parse_args()
    if not (args.tse or args.camara or args.senado):
        ap.error("escolha ao menos uma fonte: --tse, --camara, --senado")
    doc = carregar()
    if args.tse:
        print("== TSE"); fetch_tse(doc, args.dry_run)
    if args.camara:
        print("== Câmara"); fetch_camara(doc, args.dry_run)
    if args.senado:
        print("== Senado"); fetch_senado(doc, args.dry_run)
    print("agora rode: python3 scripts/build_bundle.py")


if __name__ == "__main__":
    main()
