#!/usr/bin/env python3
"""Extrai as fotos de urna dos zips do TSE (data/cache/foto_cand2026_*_div.zip),
reduz para miniaturas e grava o caminho em cada ficha de data/candidatos.json.

    python3 scripts/preparar_fotos.py            # miniaturas de 120 px em data/fotos/
    python3 scripts/preparar_fotos.py --largura 160

Redução: usa o `sips` (nativo do macOS) ou o Pillow, se estiver instalado.
Sem nenhum dos dois, copia a foto original (uns 6 KB cada, ainda aceitável).
As fotos ficam em data/fotos/<tse_id>.jpg e entram no repositório, porque o
GitHub Pages precisa delas. O build_artifact.py embute as miniaturas no
arquivo único.
"""
import argparse
import json
import pathlib
import re
import shutil
import subprocess
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
FOTOS = ROOT / "data" / "fotos"
CAND = ROOT / "data" / "candidatos.json"


def reduzir(origem: pathlib.Path, destino: pathlib.Path, largura: int) -> str:
    try:
        from PIL import Image  # type: ignore
        im = Image.open(origem).convert("RGB")
        im.thumbnail((largura, largura * 2))
        im.save(destino, "JPEG", quality=78, optimize=True)
        return "pillow"
    except ImportError:
        pass
    if shutil.which("sips"):
        shutil.copy(origem, destino)
        r = subprocess.run(["sips", "--resampleWidth", str(largura), "-s", "format", "jpeg", "-s", "formatOptions", "78", str(destino), "--out", str(destino)], capture_output=True)
        if r.returncode == 0:
            return "sips"
    shutil.copy(origem, destino)
    return "cópia"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--largura", type=int, default=120)
    a = ap.parse_args()
    zips = sorted(CACHE.glob("foto_cand2026_*_div.zip"))
    if not zips:
        raise SystemExit("nenhum foto_cand2026_*_div.zip em data/cache/")
    doc = json.loads(CAND.read_text(encoding="utf-8"))
    por_sq = {str(c.get("tse_id")): c for c in doc["candidatos"] if c.get("tse_id")}
    FOTOS.mkdir(parents=True, exist_ok=True)
    tmp = FOTOS / "_tmp"
    tmp.mkdir(exist_ok=True)
    feitos, metodo, total_kb = 0, None, 0
    for zp in zips:
        with zipfile.ZipFile(zp) as z:
            for nome in z.namelist():
                m = re.search(r"(\d{11,12})", nome)
                if not m or not nome.lower().endswith((".jpg", ".jpeg", ".png")):
                    continue
                c = por_sq.get(m.group(1))
                if not c:
                    continue
                bruto = tmp / pathlib.Path(nome).name
                with z.open(nome) as fh, open(bruto, "wb") as out:
                    shutil.copyfileobj(fh, out)
                destino = FOTOS / f"{m.group(1)}.jpg"
                metodo = reduzir(bruto, destino, a.largura)
                c["foto"] = f"data/fotos/{m.group(1)}.jpg"
                total_kb += destino.stat().st_size // 1024
                feitos += 1
    shutil.rmtree(tmp, ignore_errors=True)
    CAND.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{feitos} fotos em data/fotos/ ({total_kb} KB no total, redução via {metodo}). Ficha atualizada com o campo 'foto'.")
    print("agora rode: python3 scripts/build_bundle.py")


if __name__ == "__main__":
    main()
