#!/usr/bin/env python3
"""Interpreta, com um modelo de linguagem via OpenRouter, as certidões que listam processo.

O ler_pdfs/ocr_certidoes só dizem "tem processo" ou "nada consta". Este script pega o
texto (OCR ou pypdf) das certidões marcadas 'com apontamentos' (e das 'indeterminada'
que têm texto) e pergunta ao modelo, certidão por certidão:

  - que documento é (certidão geral, certidão de objeto e pé, print do PJe, quitação)
  - cada processo listado: número, classe, órgão, assunto ou crime, situação
  - EM QUE POLO O CANDIDATO ESTÁ (réu, autor/querelante, vítima, apelante, impetrante...)
  - o que a certidão não diz, e se o OCR está bom o bastante para confiar

Depois faz um resumo por candidato. Tudo vai para data/certidoes_interpretacao.json
(um arquivo separado de candidatos.json, para os coletores não apagarem), e o
build_bundle.py mostra na ficha como "interpretação automática".

Antes de enviar, o texto passa por uma limpeza que tira CPF, RG, título de eleitor,
data de nascimento, filiação, endereço, e-mail e telefone. O nome do candidato vai,
porque sem ele não dá para saber o polo.

Uso:
    cp chaves.env.exemplo chaves.env   # e preencha OPENROUTER_API_KEY
    python3 scripts/interpretar_certidoes.py --dry-run          # mostra o que seria enviado, sem gastar
    python3 scripts/interpretar_certidoes.py                    # todos os candidatos com apontamentos
    python3 scripts/interpretar_certidoes.py --candidato helder # só um (busca por parte do nome)
    python3 scripts/interpretar_certidoes.py --modelo google/gemini-2.5-pro
    python3 scripts/build_bundle.py

Modelo: OPENROUTER_MODEL ou --modelo. O padrão está em MODELO_PADRAO; se o OpenRouter
responder 404 "model not found", pegue o id exato em https://openrouter.ai/models.
As respostas ficam em cache em data/cache/interp/ (chave = modelo + texto), então rodar
de novo não paga de novo, a menos que mude o modelo ou o texto.

Volume esperado no ES: uns 75 documentos, 150 a 250 mil tokens no total.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _chaves  # noqa: E402,F401  (lê chaves.env)
from ler_pdfs import CACHE, CAND, ROOT, RE_SQ, mascarar_pessoais, texto_pdf  # noqa: E402

SAIDA = ROOT / "data" / "certidoes_interpretacao.json"
OCR_CACHE = CACHE / "ocr"
INTERP_CACHE = CACHE / "interp"
URL = "https://openrouter.ai/api/v1/chat/completions"
MODELO_PADRAO = "anthropic/claude-sonnet-4.5"
MAX_CHARS_DOC = 24_000   # ~6k tokens; certidão maior que isso é lista longa de processos, cortamos o fim

# ------------------------------------------------------------------ limpeza

RE_LINHAS_PESSOAIS = re.compile(
    r"(nome\s+d[oa]\s+(m[ãa]e|pai)|filia[çc][ãa]o|t[íi]tulo\s+de\s+eleitor|rg\b[^\n]{0,20}|carteira\s+profissional|"
    r"logradouro|endere[çc]o|bairro|complemento|n[úu]mero\s*:|cep\s*:|munic[íi]pio\s*:|e-?mail|telefone[^\n]{0,15}|celular|"
    r"estado\s+civil|nacionalidade|profiss[ãa]o)\s*:?\s*[^\n]*", re.I)
RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
RE_FONE = re.compile(r"\(?\d{2}\)?\s?9?\d{4}-\d{4}")
RE_TITULO = re.compile(r"\b\d{12}\b")


def limpar_para_envio(texto: str) -> str:
    t = mascarar_pessoais(texto)
    t = RE_LINHAS_PESSOAIS.sub(lambda m: m.group(1) + ": [omitido]", t)
    t = RE_EMAIL.sub("[email]", t)
    t = RE_FONE.sub("[telefone]", t)
    t = RE_TITULO.sub("[número omitido]", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    if len(t) > MAX_CHARS_DOC:
        t = t[:MAX_CHARS_DOC] + "\n[... texto cortado ...]"
    return t


# ------------------------------------------------------------------ prompts

SISTEMA_DOC = """Você é um assistente jurídico brasileiro lendo certidões criminais anexadas ao registro de candidatura no TSE (eleições 2026). O texto veio de OCR e pode ter erros de leitura.

Responda SOMENTE com um JSON válido, sem comentários nem markdown, neste formato:
{
  "tipo_documento": "certidão negativa geral | certidão positiva geral | certidão de objeto e pé | print do PJe ou de sistema | quitação eleitoral | ofício ou petição | outro",
  "orgao_emissor": "ex.: TJES 2º grau, 4ª Vara Criminal de Cachoeiro, Justiça Federal ES, TRE-ES",
  "processos": [
    {
      "numero": "número CNJ exatamente como aparece, ou null",
      "classe": "ex.: ação penal, apelação criminal, habeas corpus, termo circunstanciado, ação de improbidade, ação popular, registro de candidatura",
      "assunto": "crime ou assunto, se o texto diz; senão null",
      "orgao": "vara, câmara ou juízo, se o texto diz",
      "polo_candidato": "réu | autor ou querelante | vítima | apelante | apelado | impetrante ou paciente | requerente | só mencionado | não diz",
      "situacao": "em andamento | arquivado ou baixado | absolvido | condenado | extinta a punibilidade | transitado em julgado | suspenso | não diz",
      "data": "data de distribuição ou da última movimentação, se aparece, senão null",
      "criminal": true ou false (false para cível, eleitoral administrativo, registro de candidatura)
    }
  ],
  "nao_diz": ["o que um eleitor gostaria de saber e a certidão não informa"],
  "qualidade_ocr": "boa | média | ruim",
  "observacao": "uma frase, se houver algo importante fora dos campos acima; senão null"
}

Regras:
- Não invente. Se o texto não diz o polo ou a situação, escreva "não diz".
- "Réu" só quando o texto indica isso (RÉU:, DENUNCIADO, ACUSADO, APELANTE em apelação criminal contra sentença condenatória, PACIENTE em habeas corpus). Se o candidato aparece como QUERELANTE, AUTOR, REQUERENTE de ação popular ou VÍTIMA, marque isso.
- Certidão de objeto e pé é sobre UM processo e costuma dizer a fase. Aproveite.
- Número CNJ com o 14º dígito 6 (formato NNNNNNN-DD.AAAA.6.TR.OOOO) é Justiça Eleitoral: registro de candidatura, multa, prestação de contas. Não é criminal, salvo se o texto disser "crime eleitoral".
- Se a certidão diz "nada consta" e não lista processo, devolva "processos": [].
"""

SISTEMA_RESUMO = """Você é um assistente jurídico brasileiro. Recebe a interpretação, certidão por certidão, das certidões criminais de um candidato, já em JSON. Escreva para um eleitor leigo.

Responda SOMENTE com um JSON válido:
{
  "resumo": "2 a 4 frases em português simples. Diga quantos processos criminais existem com o candidato como réu, o que são (classe e crime, quando se sabe), em que pé estão, e o que aparece só como autor, vítima ou cível. Não repita número de processo aqui.",
  "processos_como_reu": número inteiro,
  "processos_ativos_como_reu": número inteiro,
  "condenacao": true, false ou null (null se as certidões não permitem saber),
  "confianca": "alta | média | baixa",
  "atencao": ["pontos que o eleitor deveria conferir no site do tribunal, cada um em uma frase"]
}

Regras:
- Conte o mesmo processo uma vez só, mesmo que apareça em várias certidões (1º grau, 2º grau, objeto e pé).
- Não use adjetivos. Não conclua culpa nem inocência. Processo em andamento não é condenação.
- Se o polo é "não diz" em tudo, diga isso no resumo e ponha confiança baixa.
"""


# ------------------------------------------------------------------ OpenRouter

def chamar_modelo(modelo: str, sistema: str, usuario: str, chave: str, tentativas: int = 4) -> tuple[dict, dict]:
    """Devolve (json_da_resposta, usage). Levanta SystemExit em erro definitivo."""
    corpo = json.dumps({
        "model": modelo,
        "temperature": 0,
        "max_tokens": 4000,
        "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
        "usage": {"include": True},
    }).encode("utf-8")
    req = urllib.request.Request(URL, data=corpo, method="POST", headers={
        "Authorization": f"Bearer {chave}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/elainecro/estudo_candidatos_2026",
        "X-Title": "estudo_candidatos_2026",
    })
    for i in range(tentativas):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                resp = json.loads(r.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            texto = e.read().decode("utf-8", "replace")[:500]
            if e.code == 404:
                raise SystemExit(f"modelo '{modelo}' não encontrado no OpenRouter. Veja o id exato em https://openrouter.ai/models\n{texto}")
            if e.code in (401, 403):
                raise SystemExit(f"chave recusada ({e.code}). Confira OPENROUTER_API_KEY.\n{texto}")
            if e.code in (402,):
                raise SystemExit(f"sem crédito no OpenRouter ({e.code}).\n{texto}")
            if e.code in (429, 500, 502, 503, 524) and i < tentativas - 1:
                espera = 2 ** (i + 1)
                print(f"    HTTP {e.code}, tentando de novo em {espera}s", flush=True)
                time.sleep(espera)
                continue
            raise SystemExit(f"HTTP {e.code}: {texto}")
        except (urllib.error.URLError, TimeoutError) as e:
            if i < tentativas - 1:
                time.sleep(2 ** (i + 1))
                continue
            raise SystemExit(f"rede: {e}")
    if "error" in resp:
        raise SystemExit(f"erro do OpenRouter: {resp['error']}")
    conteudo = resp["choices"][0]["message"]["content"]
    return extrair_json(conteudo), resp.get("usage") or {}


def extrair_json(texto: str) -> dict:
    t = texto.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            return json.loads(m.group(0))
        raise SystemExit(f"o modelo não devolveu JSON:\n{texto[:800]}")


def com_cache(chave_cache: str, fn):
    INTERP_CACHE.mkdir(parents=True, exist_ok=True)
    arq = INTERP_CACHE / (hashlib.sha1(chave_cache.encode("utf-8")).hexdigest() + ".json")
    if arq.exists():
        d = json.loads(arq.read_text(encoding="utf-8"))
        return d["resposta"], d.get("usage") or {}, True
    resposta, usage = fn()
    arq.write_text(json.dumps({"resposta": resposta, "usage": usage}, ensure_ascii=False, indent=1), encoding="utf-8")
    return resposta, usage, False


# ------------------------------------------------------------------ texto das certidões

def texto_certidao(item: dict) -> str:
    """arquivo = 'data/cache/<zip>:<nome dentro do zip>'. Cache de OCR primeiro, senão pypdf."""
    ref = item.get("arquivo") or ""
    if ":" not in ref:
        return ""
    zip_rel, nome = ref.split(":", 1)
    zp = ROOT / zip_rel
    cache = OCR_CACHE / zp.stem / (pathlib.Path(nome).name + ".txt")
    if cache.exists():
        t = cache.read_text(encoding="utf-8")
        if len(t.strip()) >= 20:
            return t
    if zp.exists():
        with zipfile.ZipFile(zp) as z:
            if nome in z.namelist():
                t, _ = texto_pdf(z.read(nome), max_paginas=4)
                return t
    return ""


def normal(s: str) -> str:
    import unicodedata
    return "".join(ch for ch in unicodedata.normalize("NFD", s or "") if unicodedata.category(ch) != "Mn").lower()


def selecionar(doc: dict, filtro: str | None) -> list[dict]:
    out = []
    for c in doc["candidatos"]:
        if not c.get("tse_id") or not c.get("certidoes_resumo"):
            continue
        if filtro and normal(filtro) not in normal(c["nome_urna"]) and normal(filtro) not in normal(c.get("nome_completo", "")):
            continue
        itens = [x for x in c["certidoes_resumo"] if x["status"] in ("com apontamentos", "indeterminada")]
        if c.get("certidoes_flag") == "com apontamentos" or (c.get("certidoes_flag") == "indeterminada" and itens):
            out.append(c)
    return out


# ------------------------------------------------------------------ principal

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidato", help="parte do nome de urna ou completo")
    ap.add_argument("--modelo", default=os.environ.get("OPENROUTER_MODEL", MODELO_PADRAO))
    ap.add_argument("--dry-run", action="store_true", help="não chama o modelo; mostra o que iria e uma estimativa de tokens")
    ap.add_argument("--refazer", action="store_true", help="ignora o cache de respostas")
    a = ap.parse_args()

    chave = os.environ.get("OPENROUTER_API_KEY")
    if not chave and not a.dry_run:
        raise SystemExit("falta OPENROUTER_API_KEY: preencha em chaves.env (modelo em chaves.env.exemplo) ou use --dry-run")
    if a.refazer and INTERP_CACHE.exists():
        for f in INTERP_CACHE.glob("*.json"):
            f.unlink()

    doc = json.loads(CAND.read_text(encoding="utf-8"))
    cands = selecionar(doc, a.candidato)
    if not cands:
        raise SystemExit("nenhum candidato com certidão a interpretar" + (f" para '{a.candidato}'" if a.candidato else ""))
    saida = json.loads(SAIDA.read_text(encoding="utf-8")) if SAIDA.exists() else {}
    print(f"modelo: {a.modelo}  |  {len(cands)} candidatos")

    tot_docs = tot_chars = 0
    tokens_in = tokens_out = 0
    custo = 0.0
    hoje = dt.date.today().isoformat()
    for c in cands:
        itens = [x for x in c["certidoes_resumo"] if x["status"] in ("com apontamentos", "indeterminada")]
        print(f"\n== {c['nome_urna']} ({c['cargo']}, {c['partido']}): {len(itens)} certidões", flush=True)
        interpretacoes = []
        for x in itens:
            texto = texto_certidao(x)
            if len(texto.strip()) < 20:
                print(f"   sem texto: {x['arquivo'].split(':')[-1]}")
                continue
            limpo = limpar_para_envio(texto)
            tot_docs += 1; tot_chars += len(limpo)
            if a.dry_run:
                print(f"   {x['arquivo'].split(':')[-1]}: {len(limpo):,} caracteres")
                continue
            usuario = f"Candidato: {c.get('nome_completo') or c['nome_urna']} (nome de urna: {c['nome_urna']}).\n\nTexto da certidão:\n\n{limpo}"
            resp, usage, cacheado = com_cache(f"doc|{a.modelo}|{usuario}", lambda: chamar_modelo(a.modelo, SISTEMA_DOC, usuario, chave))
            tokens_in += usage.get("prompt_tokens", 0); tokens_out += usage.get("completion_tokens", 0); custo += float(usage.get("cost") or 0)
            resp["arquivo"] = x["arquivo"]
            resp["status_heuristica"] = x["status"]
            interpretacoes.append(resp)
            np_ = len(resp.get("processos") or [])
            polos = sorted({(p.get("polo_candidato") or "?") for p in resp.get("processos") or []})
            print(f"   {'cache ' if cacheado else ''}{resp.get('tipo_documento')}: {np_} processo(s) {polos}", flush=True)
        if a.dry_run or not interpretacoes:
            continue
        usuario = f"Candidato: {c.get('nome_completo') or c['nome_urna']} (nome de urna: {c['nome_urna']}), candidato a {c['cargo']}.\n\nInterpretações das certidões:\n\n" + json.dumps(interpretacoes, ensure_ascii=False, indent=1)
        resumo, usage, cacheado = com_cache(f"resumo|{a.modelo}|{usuario}", lambda: chamar_modelo(a.modelo, SISTEMA_RESUMO, usuario, chave))
        tokens_in += usage.get("prompt_tokens", 0); tokens_out += usage.get("completion_tokens", 0); custo += float(usage.get("cost") or 0)
        saida[str(c["tse_id"])] = {
            "nome_urna": c["nome_urna"], "modelo": a.modelo, "data": hoje,
            "resumo": resumo.get("resumo"), "processos_como_reu": resumo.get("processos_como_reu"),
            "processos_ativos_como_reu": resumo.get("processos_ativos_como_reu"), "condenacao": resumo.get("condenacao"),
            "confianca": resumo.get("confianca"), "atencao": resumo.get("atencao") or [],
            "certidoes": interpretacoes,
        }
        print(f"   -> réu em {resumo.get('processos_como_reu')} ({resumo.get('processos_ativos_como_reu')} ativos), confiança {resumo.get('confianca')}")
        print(f"      {resumo.get('resumo')}")
        SAIDA.write_text(json.dumps(saida, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")  # checkpoint

    if a.dry_run:
        print(f"\n{tot_docs} documentos, {tot_chars:,} caracteres (~{tot_chars // 3:,} tokens de entrada, mais uns 30% de prompt e saída). Nada foi enviado.")
        return 0
    print(f"\n{tot_docs} documentos. Tokens: {tokens_in:,} entrada, {tokens_out:,} saída." + (f" Custo informado pelo OpenRouter: US$ {custo:.4f}" if custo else ""))
    print(f"gravado: {SAIDA.relative_to(ROOT)}. Agora rode: python3 scripts/build_bundle.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
