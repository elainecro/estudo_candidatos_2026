#!/usr/bin/env python3
"""Mostra, para cada zip em data/cache/, os CSVs que ele contém, as colunas e a
primeira linha. Serve para conferir o formato antes de escrever um leitor.

    python3 scripts/inspecionar_cache.py            # todos os zips
    python3 scripts/inspecionar_cache.py historico  # só os que têm 'historico' no nome
"""
import csv
import io
import pathlib
import sys
import zipfile

CACHE = pathlib.Path(__file__).resolve().parent.parent / "data" / "cache"
filtro = sys.argv[1].lower() if len(sys.argv) > 1 else ""

for zp in sorted(CACHE.glob("*.zip")):
    if filtro and filtro not in zp.name.lower():
        continue
    print(f"\n### {zp.name} ({zp.stat().st_size // 1024} KB)")
    try:
        with zipfile.ZipFile(zp) as z:
            nomes = z.namelist()
            csvs = [n for n in nomes if n.lower().endswith(".csv")]
            outros = [n for n in nomes if not n.lower().endswith(".csv")]
            if outros:
                print(f"  {len(outros)} arquivos não-CSV, ex.: {outros[:3]}")
            for n in csvs:
                if "_ES" not in n.upper() and "_BR" not in n.upper() and len(csvs) > 3:
                    continue
                with z.open(n) as fh:
                    txt = io.TextIOWrapper(fh, encoding="latin-1", newline="")
                    r = csv.reader(txt, delimiter=";")
                    cab = next(r, [])
                    linha = next(r, [])
                print(f"  - {n}: {len(cab)} colunas")
                print("    colunas:", ", ".join(cab))
                if linha:
                    print("    exemplo:", " | ".join(f"{c}={v[:40]}" for c, v in zip(cab, linha) if v and v not in ("#NULO#", "#NE#", "-1")))
    except zipfile.BadZipFile:
        print("  não é um zip válido")
