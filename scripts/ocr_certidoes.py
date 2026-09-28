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
    python3 scripts/ocr_certidoes.py --debug             # uma certidão, passo a passo (comece por aqui)
    python3 scripts/ocr_certidoes.py --limite 50         # teste rápido
    python3 scripts/ocr_certidoes.py --todas             # refaz até as que já tinham texto

O texto OCR de cada PDF fica em data/cache/ocr/ (fora do git), então rodar de novo
é rápido. Depois: python3 scripts/build_bundle.py

Tempo: umas 3.800 certidões com 1 a 3 páginas cada dá algo entre 20 e 60 minutos
no Vision. Pode interromper com Ctrl+C: o que já foi lido fica salvo, e a rodada
seguinte pula o que já está em data/cache/ocr/. Se parecer travado, rode com
OCR_VERBOSE=1 na frente para ver qual arquivo está sendo lido.

A leitura é heurística. "Com apontamentos" quer dizer que a certidão lista processo;
pode ser arquivado, ou a pessoa pode ser vítima ou testemunha. Sempre confira o PDF.
"""
import argparse
import io
import os
import pathlib
import subprocess
import sys
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ler_pdfs import CACHE, CAND, ROOT, RE_SQ, carregar, classificar_certidao, reflag, salvar, texto_pdf  # noqa: E402

OCR_CACHE = CACHE / "ocr"
VERBOSE = bool(os.environ.get("OCR_VERBOSE"))  # OCR_VERBOSE=1 imprime cada arquivo antes de ler
DPI = 200            # 200 dpi costuma bastar para certidão impressa; 300 é mais lento e raramente melhora
MAX_PAGINAS = 4      # certidões têm 1 a 3 páginas; o resto costuma ser assinatura digital
MAX_LADO_PX = 2600   # teto para o maior lado da imagem renderizada
MIN_CARACTERES = 200  # abaixo disso o pypdf provavelmente só pegou cabeçalho; vai para o OCR


# ---------------------------------------------------------------- motores

class MotorVision:
    """macOS: PDFKit renderiza, Vision lê. Zero dependência além do pyobjc."""
    nome = "vision"

    def __init__(self):
        if sys.platform != "darwin":
            raise RuntimeError("Vision só existe no macOS")
        try:
            import Quartz  # noqa: F401
            import Vision  # noqa: F401
            from Foundation import NSData  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("pip3 install pyobjc-framework-Vision pyobjc-framework-Quartz") from exc
        self.falhas: dict[str, int] = {}

    def _falha(self, motivo: str) -> None:
        self.falhas[motivo] = self.falhas.get(motivo, 0) + 1

    def ocr_pdf(self, dados: bytes, debug: bool = False) -> str:
        import objc

        # Sem isso, cada TIFF de ~15 MB fica retido até o fim do processo e a
        # memória explode depois de umas centenas de certidões.
        with objc.autorelease_pool():
            return self._ocr_pdf(dados, debug)

    def _ocr_pdf(self, dados: bytes, debug: bool = False) -> str:
        import Quartz
        from Foundation import NSData, NSMakeSize

        nsdata = NSData.dataWithBytes_length_(dados, len(dados))
        doc = Quartz.PDFDocument.alloc().initWithData_(nsdata)
        if doc is None:
            self._falha("PDFDocument não abriu o PDF")
            return ""
        n = doc.pageCount()
        if debug:
            print(f"    páginas no PDF: {n}")
        partes = []
        for i in range(min(n, MAX_PAGINAS)):
            pagina = doc.pageAtIndex_(i)
            box = pagina.boundsForBox_(0)  # 0 = kPDFDisplayBoxMediaBox
            escala = DPI / 72.0
            maior = max(box.size.width, box.size.height) * escala
            if maior > MAX_LADO_PX:  # página gigante (scan em resolução alta): reduz
                escala *= MAX_LADO_PX / maior
            tamanho = NSMakeSize(box.size.width * escala, box.size.height * escala)
            img = pagina.thumbnailOfSize_forBox_(tamanho, 0)
            if img is None:
                self._falha("thumbnailOfSize devolveu None")
                continue
            tiff = img.TIFFRepresentation()
            if tiff is None or tiff.length() == 0:
                self._falha("TIFFRepresentation vazio")
                continue
            if debug:
                print(f"    página {i + 1}: {int(tamanho.width)}x{int(tamanho.height)} px, tiff {tiff.length() // 1024} KB")
            partes.append(self._ocr_data(tiff, debug))
        return "\n".join(partes)

    def _ocr_data(self, nsdata, debug: bool = False) -> str:
        import Vision

        req = Vision.VNRecognizeTextRequest.alloc().init()
        req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        req.setUsesLanguageCorrection_(True)
        try:
            req.setRecognitionLanguages_(["pt-BR"])
        except Exception:  # noqa: BLE001  (versões antigas do macOS não têm pt-BR)
            self._falha("setRecognitionLanguages pt-BR não aceito")
        handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(nsdata, None)
        if handler is None:
            self._falha("VNImageRequestHandler não aceitou a imagem")
            return ""
        ok, erro = handler.performRequests_error_([req], None)
        if not ok:
            self._falha(f"performRequests falhou: {erro}")
            return ""
        resultados = req.results() or []
        if debug:
            print(f"    Vision: {len(resultados)} linhas reconhecidas")
        linhas = []
        for obs in resultados:
            cand = obs.topCandidates_(1)
            if cand:
                linhas.append(str(cand[0].string()))
        if not linhas:
            self._falha("Vision não reconheceu nenhuma linha")
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
        self.falhas: dict[str, int] = {}
        if self.lang == "eng":
            print("aviso: tesseract sem o pacote 'por'; usando inglês, acentos podem sair errados", file=sys.stderr)

    def ocr_pdf(self, dados: bytes, debug: bool = False) -> str:
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
        t = cache.read_text(encoding="utf-8")
        if len(t.strip()) >= 20:
            return t, "cache"
        # cache vazio: OCR anterior falhou, tenta de novo
    dados = zp.read(nome)
    texto, _ = texto_pdf(dados, max_paginas=MAX_PAGINAS)
    if len(texto.strip()) >= MIN_CARACTERES and not forcar:
        return texto, "pdf"            # já tinha texto; OCR não ia ajudar
    texto = motor.ocr_pdf(dados)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(texto, encoding="utf-8")
    return texto, "ocr"


def depurar(motor, zp_path: pathlib.Path, por_sq: dict) -> int:
    """OCR de uma única certidão, com cada etapa impressa. Não grava nada."""
    with zipfile.ZipFile(zp_path) as zp:
        for nome in zp.namelist():
            m = RE_SQ.search(nome)
            if nome.lower().endswith(".pdf") and m and m.group(1) in por_sq:
                break
        else:
            print("nenhum PDF do zip bate com um candidato"); return 1
        c = por_sq[m.group(1)]
        dados = zp.read(nome)
        print(f"arquivo: {nome} ({len(dados) // 1024} KB), candidato: {c.get('nome_urna')} ({c.get('cargo')})")
        texto_pdf_, _ = texto_pdf(dados, max_paginas=MAX_PAGINAS)
        print(f"texto embutido no PDF (pypdf): {len(texto_pdf_.strip())} caracteres")
        texto = motor.ocr_pdf(dados, debug=True)
        print(f"texto do OCR: {len(texto)} caracteres")
        print("-" * 60); print(texto[:1500]); print("-" * 60)
        print("classificação:", classificar_certidao(texto))
        if getattr(motor, "falhas", None):
            print("falhas registradas:", motor.falhas)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--motor", choices=["vision", "tesseract"])
    ap.add_argument("--todas", action="store_true", help="refaz também as certidões que já tinham texto ou OCR")
    ap.add_argument("--cargo", help="só candidatos a esse cargo (ex: governador, senador)")
    ap.add_argument("--limite", type=int, help="para depois de N certidões processadas por OCR")
    ap.add_argument("--debug", action="store_true", help="faz OCR de UMA certidão, imprimindo cada etapa e o texto lido, e sai sem gravar")
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
    if a.debug:
        return depurar(motor, zips[0], por_sq)
    feitos = ocrs = mudaram = vazios = 0
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
                    if VERBOSE:
                        print(f"    {nome}", flush=True)
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
                        if len(texto.strip()) < 20:
                            vazios += 1
                        if ocrs % 25 == 0:
                            print(f"  {ocrs} OCRs feitos ({feitos} certidões revistas)", flush=True)
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
    if vazios:
        print(f"ATENÇÃO: {vazios} OCRs devolveram texto vazio. Motivos registrados pelo motor:")
        for motivo, n in sorted(getattr(motor, "falhas", {}).items(), key=lambda kv: -kv[1]):
            print(f"  {n:5d}  {motivo}")
        print("Rode com --debug para ver uma certidão passo a passo.")
    print("Candidatos por situação: " + ", ".join(f"{k}: {v}" for k, v in sorted(flags.items())))
    print(f"gravado: {CAND.relative_to(ROOT)}. Agora rode: python3 scripts/build_bundle.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
