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
FILES = {"cargos": "cargos.json", "partidos": "partidos.json", "candidatos": "candidatos.json"}


def main() -> int:
    bundle = {}
    for key, name in FILES.items():
        path = DATA / name
        try:
            bundle[key] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"JSON inválido em {path}: {exc}", file=sys.stderr)
            return 1
    validar(bundle)
    embutir_propostas(bundle)
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


def validar(bundle: dict) -> None:
    siglas = {p["sigla"] for p in bundle["partidos"]["partidos"]}
    for c in bundle["candidatos"]["candidatos"]:
        c["partido"] = SIGLAS.get(str(c.get("partido") or "").upper(), c.get("partido"))
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
