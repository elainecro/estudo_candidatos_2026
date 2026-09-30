#!/usr/bin/env python3
"""Empacota data/*.json em data/bundle.js para a página funcionar aberta direto
do disco (file://), sem servidor. Rode depois de editar qualquer JSON:

    python3 scripts/build_bundle.py
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FILES = {"cargos": "cargos.json", "partidos": "partidos.json", "candidatos": "candidatos.json", "espectros": "espectros.json"}


def main() -> int:
    bundle = {}
    for key, name in FILES.items():
        path = DATA / name
        try:
            bundle[key] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"JSON inválido em {path}: {exc}", file=sys.stderr)
            return 1
    fundir_duplicatas(bundle)
    validar(bundle)
    embutir_propostas(bundle)
    embutir_resumos(bundle)
    sanear_tse(bundle)
    descartar_camara_homonima(bundle)
    separar_pecs(bundle)
    sanear_certidoes(bundle)
    embutir_interpretacoes(bundle)
    embutir_biografias(bundle)
    out = DATA / "bundle.js"
    out.write_text(
        "// Gerado por scripts/build_bundle.py. Não edite à mão; edite os JSON em data/.\n"
        "window.ESTUDO_2026 = " + json.dumps(bundle, ensure_ascii=False, indent=None) + ";\n",
        encoding="utf-8",
    )
    n = len(bundle["candidatos"]["candidatos"])
    print(f"ok: {out.relative_to(ROOT)} ({n} candidatos, {len(bundle['partidos']['partidos'])} partidos)")
    return 0


SIGLAS = {"AVANTE": "Avante", "PODE": "Podemos", "PODEMOS": "Podemos", "REPUBLICANOS": "Republicanos", "UNIÃO": "União", "UNIAO": "União",
          "NOVO": "Novo", "SOLIDARIEDADE": "Solidariedade", "CIDADANIA": "Cidadania", "REDE": "Rede", "MISSÃO": "Missão", "MISSAO": "Missão",
          "DEMOCRATA": "Democrata", "MOBILIZA": "Mobiliza", "PC DO B": "PCdoB", "PCDOB": "PCdoB", "AGIR": "Agir"}


def embutir_propostas(bundle: dict, limite: int = 200_000) -> None:
    """Coloca o texto extraído do plano de governo (data/propostas/*.txt) dentro da ficha."""
    n = 0
    for c in bundle["candidatos"]["candidatos"]:
        pg = c.get("proposta_governo")
        if not pg or not pg.get("arquivo"):
            continue
        arq = ROOT / pg["arquivo"]
        if arq.exists():
            txt = arq.read_text(encoding="utf-8")
            pg["texto"] = txt[:limite] + ("\n\n[texto cortado; veja o PDF original no DivulgaCand]" if len(txt) > limite else "")
            n += 1
    if n:
        print(f"{n} planos de governo embutidos")


def embutir_resumos(bundle: dict) -> None:
    """Mescla data/propostas_resumo/<tse_id>.json (resumo estruturado do plano) na ficha.

    Fica em arquivo separado de propostas de candidatos.json para o resumo poder ser
    versionado sem mexer no JSON que os coletores reescrevem.
    """
    pasta = DATA / "propostas_resumo"
    if not pasta.is_dir():
        return
    por_sq = {str(c.get("tse_id")): c for c in bundle["candidatos"]["candidatos"] if c.get("tse_id")}
    n = 0
    for arq in sorted(pasta.glob("*.json")):
        c = por_sq.get(arq.stem)
        if not c:
            print(f"aviso: {arq.name} não bate com nenhum tse_id em candidatos.json", file=sys.stderr)
            continue
        try:
            r = json.loads(arq.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"JSON inválido em {arq}: {exc}")
        for k in ("sintese", "eixos"):
            if k not in r:
                raise SystemExit(f"{arq.name}: falta o campo '{k}'")
        c["proposta_resumo"] = r
        n += 1
    if n:
        print(f"{n} resumos de plano de governo embutidos")


def embutir_interpretacoes(bundle: dict) -> None:
    """Mescla data/certidoes_interpretacao.json (saída do interpretar_certidoes.py) na ficha."""
    arq = DATA / "certidoes_interpretacao.json"
    if not arq.exists():
        return
    interp = json.loads(arq.read_text(encoding="utf-8"))
    n = 0
    for c in bundle["candidatos"]["candidatos"]:
        it = interp.get(str(c.get("tse_id")))
        if it and c.get("certidoes_resumo"):
            c["certidoes_interpretacao"] = it
            n += 1
    if n:
        print(f"{n} interpretações de certidões embutidas")


RE_MARCADOR = __import__("re").compile(r"#NULO#?|#NE#?", __import__("re").I)


def embutir_biografias(bundle: dict) -> None:
    """Mescla data/biografias/<tse_id>.json (trajetória pesquisada na web) na ficha como 'trajetoria'."""
    pasta = DATA / "biografias"
    if not pasta.is_dir():
        return
    por_sq = {str(c.get("tse_id")): c for c in bundle["candidatos"]["candidatos"] if c.get("tse_id")}
    n = 0
    for arq in sorted(pasta.glob("*.json")):
        c = por_sq.get(arq.stem)
        if not c:
            print(f"aviso: biografia {arq.name} não bate com nenhum tse_id", file=sys.stderr)
            continue
        try:
            b = json.loads(arq.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"JSON inválido em {arq}: {exc}")
        if not b.get("texto"):
            continue
        c["trajetoria"] = b
        n += 1
    if n:
        print(f"{n} biografias embutidas")


def descartar_camara_homonima(bundle: dict) -> None:
    """Coletas antigas casavam o nome de urna com qualquer deputado da API (ex.: 'Lula' -> Lula da Fonte).
    Sem 'camara_nome' validado, um id da legislatura atual (>= 200000) só vale se a pessoa foi deputada
    federal a partir de 2019; senão os dados da Câmara são de homônimo e saem da ficha."""
    n = 0
    for c in bundle["candidatos"]["candidatos"]:
        cid = c.get("camara_id")
        if not cid or c.get("camara_nome") or int(cid) < 200000:
            continue
        recente = any("deputad" in (m.get("cargo") or "").lower() and "federal" in (m.get("cargo") or "").lower()
                      and any(a in (m.get("periodo") or "") for a in ("2019", "202")) for m in c.get("mandatos") or [])
        recente = recente or any((e.get("cargo") or "").lower().startswith("deputado federal") and str(e.get("ano")) >= "2018" for e in c.get("eleicoes_anteriores") or [])
        if recente or c.get("cargo") == "deputado_federal":
            continue
        for k in ("camara_id", "gastos", "comissoes", "votacoes_chave"):
            c.pop(k, None)
        if isinstance(c.get("projetos"), dict) and "Câmara" in (c["projetos"].get("fonte") or ""):
            c["projetos"] = None
        n += 1
        print(f"aviso: dados da Câmara descartados para {c['nome_urna']} (id {cid} é de homônimo); rode fetch_dados.py --camara", file=sys.stderr)
    if n:
        print(f"{n} ficha(s) com dados de deputado homônimo removidos")


def separar_pecs(bundle: dict) -> None:
    """Dados coletados antes desta regra: tira as PECs de 'apresentados/em_tramitacao/aprovados' e põe em 'pecs_assinadas'."""
    n = 0
    for c in bundle["candidatos"]["candidatos"]:
        pj = c.get("projetos")
        if not isinstance(pj, dict) or "pecs_assinadas" in pj:
            continue
        pecs = []
        for chave in ("em_tramitacao", "aprovados"):
            lista = pj.get(chave) or []
            ficam = []
            for it in lista:
                if str(it.get("id") or "").upper().startswith("PEC "):
                    it = dict(it)
                    it["situacao"] = it.pop("status", None) or "em tramitação"
                    pecs.append(it)
                else:
                    ficam.append(it)
            pj[chave] = ficam
        if pecs:
            pj["pecs_assinadas"] = pecs
            pj["pecs_obs"] = "PEC precisa de 27 assinaturas no Senado (171 na Câmara); cada signatário aparece como autor nos dados abertos."
            ap = pj.get("apresentados")
            if isinstance(ap, dict) and isinstance(ap.get("total"), int):
                ap["total"] = max(0, ap["total"] - len(pecs))
                ap["obs"] = (ap.get("obs") or "").replace(", PEC", "").replace(" e PEC", "").replace("PEC e ", "") + " PECs contadas à parte."
            n += 1
    if n:
        print(f"{n} fichas com PECs separadas dos projetos próprios")


def sanear_tse(bundle: dict) -> None:
    """Tira marcadores de vazio do TSE (#NULO, #NE) que coletas antigas deixaram nos textos."""
    n = 0
    for c in bundle["candidatos"]["candidatos"]:
        for k in ("situacao_detalhe", "situacao_obs", "federacao", "coligacao", "ocupacao"):
            v = c.get(k)
            if isinstance(v, str) and RE_MARCADOR.fullmatch(v.strip()):
                c[k] = None
                n += 1
        r = c.get("resumo")
        if isinstance(r, str) and RE_MARCADOR.search(r):
            r = __import__("re").sub(r"\s*(Federação|Coligação): (#NULO#?|#NE#?)\.", "", r, flags=__import__("re").I)
            c["resumo"] = RE_MARCADOR.sub("", r).strip()
            n += 1
        camp = c.get("campanha") or {}
        for d in camp.get("maiores_doadores") or []:
            if RE_MARCADOR.fullmatch((d.get("nome") or "").strip()):
                d["nome"] = "doador não identificado"
                n += 1
        for d in camp.get("maiores_fornecedores") or []:
            if RE_MARCADOR.fullmatch((d.get("nome") or "").strip()):
                d["nome"] = "fornecedor não identificado"
                n += 1
        for d in camp.get("despesas_por_tipo") or []:
            if RE_MARCADOR.fullmatch((d.get("tipo") or "").strip()):
                d["tipo"] = "Outros"
                n += 1
    if n:
        print(f"{n} marcadores de vazio do TSE limpos")


def sanear_certidoes(bundle: dict) -> None:
    """Mascara CPF/data de nascimento nos trechos e reclassifica certidões geradas por versões antigas."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from ler_pdfs import justica_eleitoral, mascarar_pessoais, reflag
    n = 0
    for c in bundle["candidatos"]["candidatos"]:
        for x in c.get("certidoes_resumo") or []:
            if x.get("trecho"):
                novo = mascarar_pessoais(x["trecho"])
                n += novo != x["trecho"]
                x["trecho"] = novo
            if x.get("status") == "com apontamentos" and x.get("processos") and all(justica_eleitoral(p) for p in x["processos"]):
                x["status"] = "só eleitoral"
                x["obs"] = "só processos da Justiça Eleitoral (registro de candidatura, multa, contas); não é apontamento criminal"
                x["trecho"] = None
        if c.get("certidoes_resumo"):
            reflag(c)
    if n:
        print(f"{n} trechos de certidão com dado pessoal mascarado")


def fundir_duplicatas(bundle: dict) -> None:
    """Rede de segurança: duas fichas com o mesmo tse_id (manual + importada do TSE) viram uma no site.
    A correção definitiva é no JSON: python3 scripts/fetch_dados.py --fundir."""
    importada = lambda c: (c.get("resumo") or "").startswith("Importado do TSE")
    por, fora = {}, set()
    for c in bundle["candidatos"]["candidatos"]:
        t = str(c.get("tse_id") or "")
        if not t:
            continue
        if t not in por:
            por[t] = c
            continue
        a, b = por[t], c
        if importada(a) and not importada(b):
            a, b = b, a
            por[t] = a
        for k, v in b.items():
            if k != "id" and a.get(k) in (None, "", [], {}):
                a[k] = v
        fora.add(b["id"])
        print(f"aviso: '{a['nome_urna']}' e '{b['nome_urna']}' têm o mesmo tse_id {t}; ficou uma só. Rode fetch_dados.py --fundir", file=sys.stderr)
    if fora:
        bundle["candidatos"]["candidatos"] = [c for c in bundle["candidatos"]["candidatos"] if c["id"] not in fora]


def validar(bundle: dict) -> None:
    siglas = {p["sigla"] for p in bundle["partidos"]["partidos"]}
    for c in bundle["candidatos"]["candidatos"]:
        c["partido"] = SIGLAS.get(str(c.get("partido") or "").upper(), c.get("partido"))
    espectros = {e["id"] for e in bundle["espectros"]["espectros"]}
    for p in bundle["partidos"]["partidos"]:
        if p["espectro"] not in espectros:
            raise SystemExit(f"{p['sigla']}: espectro '{p['espectro']}' não está em espectros.json ({sorted(espectros)})")
    cargos = {c["id"] for c in bundle["cargos"]["cargos"]}
    ids = set()
    for c in bundle["candidatos"]["candidatos"]:
        if c["id"] in ids:
            raise SystemExit(f"id duplicado: {c['id']}")
        ids.add(c["id"])
        if c["partido"] not in siglas:
            raise SystemExit(f"{c['id']}: partido '{c['partido']}' não está em partidos.json")
        if c["cargo"] not in cargos:
            raise SystemExit(f"{c['id']}: cargo '{c['cargo']}' não está em cargos.json")


if __name__ == "__main__":
    raise SystemExit(main())
