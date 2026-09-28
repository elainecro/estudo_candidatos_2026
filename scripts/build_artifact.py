#!/usr/bin/env python3
"""Gera um HTML único (CSS, JS e dados embutidos) para publicar como Artifact
do Claude ou em qualquer host que aceite um arquivo só.

    python3 scripts/build_bundle.py && python3 scripts/build_artifact.py [saida.html]

O arquivo gerado não tem <html>/<head>/<body>: o Artifact envolve isso sozinho.
Para hospedar em outro lugar (GitHub Pages, Netlify), use o index.html normal.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
html = (ROOT / "index.html").read_text(encoding="utf-8")
css = (ROOT / "assets" / "style.css").read_text(encoding="utf-8")
js = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
data = (ROOT / "data" / "bundle.js").read_text(encoding="utf-8")

# fotos: o arquivo único não pode referenciar data/fotos/, então embute miniaturas como data URI
import base64
import json
prefixo = "window.ESTUDO_2026 = "
ini = data.index(prefixo) + len(prefixo)
bundle = json.loads(data[ini:].rstrip().rstrip(";"))
embutidas = 0
for c in bundle["candidatos"]["candidatos"]:
    f = c.get("foto")
    if f and not str(f).startswith(("http", "data:")):
        caminho = ROOT / f
        if caminho.exists():
            c["foto"] = "data:image/jpeg;base64," + base64.b64encode(caminho.read_bytes()).decode()
            embutidas += 1
        else:
            c["foto"] = None
data = data[:ini] + json.dumps(bundle, ensure_ascii=False) + ";\n"
if embutidas:
    print(f"{embutidas} fotos embutidas")

title = re.search(r"<title>(.*?)</title>", html).group(1)
body = re.search(r"<body>(.*)</body>", html, re.S).group(1)
body = body.replace('<script src="data/bundle.js"></script>', "").replace('<script src="assets/app.js"></script>', "")

# tema explícito do visualizador (data-theme="dark") + color-scheme
dark_tokens = re.search(r"@media \(prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme=\"light\"\]\) \{(.*?)\}\s*\}", css, re.S).group(1)
css = css.replace(
    "@media (prefers-color-scheme: dark) {\n  :root:not([data-theme=\"light\"]) {",
    "@media (prefers-color-scheme: dark) {\n  :root:not([data-theme=\"light\"]) { color-scheme: dark;",
)
css += "\n:root[data-theme=\"dark\"] { color-scheme: dark;" + dark_tokens + "}\n"
css += "body { padding-block: 0; }\n.wrap { padding-inline: 16px; }\n"

out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "artifact.html"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(
    f"<title>{title}</title>\n<style>\n{css}\n</style>\n{body}\n<script>\n{data}\n</script>\n<script>\n{js}\n</script>\n",
    encoding="utf-8",
)
print(f"ok: {out} ({out.stat().st_size // 1024} KB)")
