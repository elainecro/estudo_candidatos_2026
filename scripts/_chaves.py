"""Carrega chaves.env (na raiz do projeto) para o ambiente, sem sobrescrever o que já existe.

Formato: KEY=valor, uma por linha; linhas em branco e '#' são ignorados.
O arquivo fica fora do git (.gitignore). Modelo em chaves.env.exemplo.
"""
import os
import pathlib

ARQUIVO = pathlib.Path(__file__).resolve().parent.parent / "chaves.env"


def carregar() -> int:
    if not ARQUIVO.exists():
        return 0
    n = 0
    for linha in ARQUIVO.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        k, v = linha.split("=", 1)
        k, v = k.strip(), v.strip().strip("'\"")
        if k and v and k not in os.environ:
            os.environ[k] = v
            n += 1
    return n


carregar()
