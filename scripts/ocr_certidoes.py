#!/usr/bin/env python3
"""OCR das certidões criminais que vieram como imagem escaneada.

O `ler_pdfs.py --certidoes` só consegue ler certidões com texto embutido no PDF.
No ES, 3.801 das 3.827 são PDF de imagem. Este script renderiza cada página,
passa por OCR e reclassifica a certidão com a mesma heurística do ler_pdfs.py.

Motores de OCR, na ordem em que são tentados:
  vision     macOS (Vision framework, já vem no sistema). Precisa de:
                 pip3 install pyobjc-framework-Vision pyobjc-framework-Quartz
             É o mais rápido e não instala nada pesado. Renderiza com o PDFKit.
  tesseract  Qualquer sistema. Precisa de:
                 brew install tesseract tesseract-lang   (ou apt install tesseract-ocr tesseract-ocr-por)
                 pip3 install pymupdf
Use --motor para forçar um deles.

Uso (na pasta do projeto, com certidao_criminal_2026_ES.zip em data/cache/):

    python3 scripts/ocr_certidoes.py                     # só as certidões ainda 'indeterminada'
    python3 scripts/ocr_certidoes.py --cargo governador  # começa pelos majoritários
    python3 scripts/ocr_certidoes.py --limite 50         # teste rápido
    python3 scripts/ocr_certidoes.py --todas             # refaz até as que já tinham texto

O texto OCR de cada PDF fica em data/cache/ocr/ (fora do git), então rodar de novo
é rápido. Depois: python3 scripts/build_bundle.py

Tempo: umas 3.800 certidões com 1 a 3 páginas cada dá algo entre 20 e 60 minutos
no Vision. Pode interromper com Ctrl+C: o que já foi lido fica salvo.

A leitura é heurística. "Com apontamentos" quer dizer que a certidão lista processo;
pode ser arquivado, ou a pessoa pode ser vítima ou testemunha. Sempre confira o PDF.
"""
import argparse
import io
import pathlib
import subprocess
import sys
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ler_pdfs import CACHE, CAND, ROOT, RE_SQ, carregar, classificar_certidao, salvar, texto_pdf  # noqa: E402

OCR_CACHE = CACHE / "ocr"
DPI = 200            # 200 dpi costuma bastar para certidão impressa; 300 é mais lento e raramente melhora
MAX_PAGINAS = 4      # certidões têm 1 a 3 páginas; o resto costuma ser assinatura digital
MIN_CARACTERES = 200  # abaixo disso o pypdf provavelmente só pegou cabeçalho; vai para o OCR


# ---------------------------------------------------------------- motores

class MotorVision:
    """macOS: PDFKit renderiza, Vision lê. Zero dependência além do pyobjc."""
    nome = "vision"

    def __init__(self):
        try:
            import Quartz  # noqa: F401
            import Vision  # noqa: F401
            from Foundation import NSData  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("pip3 install pyobjc-framework-Vision pyobjc-framework-Quartz") from exc
        if sys.platform != "darwin":
            raise RuntimeError("Vision só existe no macOS")

    def ocr_pdf(self, dados: bytes) -> str:
        import Quartz
        import Vision
        from Foundation import NSData

        doc = Quartz.PDFDocument.alloc().initWithData_(NSData.dataWithBytes_length_(dados, len(dados)))
        if doc is None:
            return ""
        partes = []
        for i in range(min(doc.pageCount(), MAX_PAGINAS)):
            pagina = doc.pageAtIndex_(i)
            box = pagina.boundsForBox_(Quartz.kPDFDisplayBoxMediaBox)
            escala = DPI / 72.0
            tamanho = Quartz.NSMakeSize(box.size.width * escala, box.size.height * escala)
            img = pagina.thumbnailOfSize_forBox_(tamanho, Quartz.kPDFDisplayBoxMediaBox)
            if img is None:
                continue
            cg = img.CGImageForProposedRect_context_hints_(None, None, None)
            if cg is None:
                continue
            partes.append(self._ocr_cgimage(cg))
        return "\n".join(partes)

    @staticmethod
    def _ocr_cgimage(cg) -> str:
        import Vision

        req = Vision.VNRecognizeTextRequest.alloc().init()
        req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        req.setUsesLanguageCorrection_(True)
        try:
            req.setRecognitionLanguages_(["pt-BR"])
        except Exception:  # noqa: BLE001  (versões antigas do macOS não têm pt-BR)
            pass
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg, None)
        ok, erro = handler.performRequests_error_([req], None)
        if not ok:
            return ""
        linhas = []
        for obs in req.results() or []:
            cand = obs.topCandidates_(1)
            if cand:
                linhas.append(str(cand[0].string()))
        return "\n".join(linhas)


class MotorTesseract:
    """Qualquer sistema: PyMuPDF renderiza, binário tesseract lê."""
    nome = "tesseract"

    def __init__(self):
        try:
            import fitz  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("pip3 install pymupdf") from exc
        try:
            subprocess.run(["tesseract", "--version"], capture_output=True, check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RuntimeError("instale o tesseract (brew install tesseract tesseract-lang)") from exc
        langs = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True).stdout
        self.lang = "por" if "por" in langs.split() else "eng"
        if self.lang == "eng":
            print("aviso: tesseract sem o pacote 'por'; usando inglês, acentos podem sair errados", file=sys.stderr)

    def ocr_pdf(self, dados: bytes) -> str:
        import fitz

        partes = []
        with fitz.open(stream=dados, filetype="pdf") as doc:
            for i, pagina in enumerate(doc):
                if i >= MAX_PAGINAS:
                    break
                png = pagina.get_pixmap(dpi=DPI).tobytes("png")
                partes.append(self._ocr_png(png))
        return "\n".join(partes)

    def _ocr_png(self, png: bytes) -> str:
        r = subprocess.run(["tesseract", "stdin", "stdout", "-l", self.lang, "--psm", "6"],
                           input=png, capture_output=True)
        return r.stdout.decode("utf-8", "replace")


def escolher_motor(nome: str | None):
    motores = {"vision": MotorVision, "tesseract": MotorTesseract}
    ordem = [nome] if nome else (["vision", "tesseract"] if sys.platform == "darwin" else ["tesseract", "vision"])
    erros = []
    for n in ordem:
        try:
            m = motores[n]()
            print(f"motor de OCR: {m.nome}")
            return m
        except RuntimeError as exc:
            erros.append(f"  {n}: {exc}")
    raise SystemExit("nenhum motor de OCR disponível:\n" + "\n".join(erros))


# ---------------------------------------------------------------- pipeline

def texto_da_certidao(motor, zp: zipfile.ZipFile, zip_nome: str, nome: str, forcar: bool) -> tuple[str, str]:
    """Devolve (texto, origem). Usa o cache em data/cache/ocr/ quando existe."""
    cache = OCR_CACHE / zip_nome / (pathlib.Path(nome).name + ".txt")
    if cache.exists() and not forcar:
        return cache.read_text(encoding="utf-8"), "cache"
    dados = zp.read(nome)
    texto, _ = texto_pdf(dados, max_paginas=MAX_PAGINAS)
    if len(texto.strip()) >= MIN_CARACTERES and not forcar:
        return texto, "pdf"            # já tinha texto; OCR não ia ajudar
    texto = motor.ocr_pdf(dados)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(texto, encoding="utf-8")
    return texto, "ocr"


def reflag(c: dict) -> None:
    r = c.get("certidoes_resumo") or []
    if not r:
        c.pop("certidoes_flag", None)
        return
    if any(x["status"] == "com apontamentos" for x in r):
        c["certidoes_flag"] = "com apontamentos"
    elif all(x["status"] == "nada consta" or x["tipo"] == "quitação eleitoral" for x in r):
        c["certidoes_flag"] = "nada consta"
    else:
        c["certidoes_flag"] = "indeterminada"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--motor", choices=["vision", "tesseract"])
    ap.add_argument("--todas", action="store_true", help="refaz também as certidões que já tinham texto ou OCR")
    ap.add_argument("--cargo", help="só candidatos a esse cargo (ex: governador, senador)")
    ap.add_argument("--limite", type=int, help="para depois de N certidões processadas por OCR")
    a = ap.parse_args()

    zips = sorted(CACHE.glob("certidao_criminal_2026_*.zip"))
    if not zips:
        raise SystemExit("nenhum certidao_criminal_2026_*.zip em data/cache/")
    doc = carregar()
    por_sq = {str(c.get("tse_id")): c for c in doc["candidatos"] if c.get("tse_id")}
    if a.cargo:
        por_sq = {k: c for k, c in por_sq.items() if c.get("cargo") == a.cargo}

    # índice do que já está na ficha, para atualizar no lugar
    existentes = {}
    for c in por_sq.values():
        for item in c.get("certidoes_resumo") or []:
            existentes[item.get("arquivo")] = item

    motor = escolher_motor(a.motor)
    feitos = ocrs = mudaram = 0
    try:
        for zp_path in zips:
            with zipfile.ZipFile(zp_path) as zp:
                nomes = [n for n in zp.namelist() if n.lower().endswith(".pdf")]
                print(f"{zp_path.name}: {len(nomes)} PDFs")
                for nome in nomes:
                    m = RE_SQ.search(nome)
                    c = por_sq.get(m.group(1)) if m else None
                    if not c:
                        continue
                    chave = f"data/cache/{zp_path.name}:{nome}"
                    antigo = existentes.get(chave)
                    if antigo and antigo.get("status") != "indeterminada" and not a.todas:
                        continue
                    texto, origem = texto_da_certidao(motor, zp, zp_path.stem, nome, a.todas)
                    novo = classificar_certidao(texto)
                    novo["arquivo"] = chave
                    novo["leitura"] = origem
                    if antigo:
                        if antigo.get("status") != novo["status"]:
                            mudaram += 1
                        antigo.clear()
                        antigo.update(novo)
                    else:
                        c.setdefault("certidoes_resumo", []).append(novo)
                        existentes[chave] = novo
                    feitos += 1
                    if origem == "ocr":
                        ocrs += 1
                        if ocrs % 25 == 0:
                            print(f"  {ocrs} OCRs feitos ({feitos} certidões revistas)")
                            salvar(doc)   # checkpoint
                    if a.limite and ocrs >= a.limite:
                        raise KeyboardInterrupt
    except KeyboardInterrupt:
        print("\ninterrompido; salvando o que já foi lido")

    for c in por_sq.values():
        reflag(c)
    salvar(doc)

    flags = {}
    for c in por_sq.values():
        flags[c.get("certidoes_flag", "sem certidão")] = flags.get(c.get("certidoes_flag", "sem certidão"), 0) + 1
    print(f"\n{feitos} certidões revistas, {ocrs} por OCR, {mudaram} mudaram de status.")
    print("Candidatos por situação: " + ", ".join(f"{k}: {v}" for k, v in sorted(flags.items())))
    print(f"gravado: {CAND.relative_to(ROOT)}. Agora rode: python3 scripts/build_bundle.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
