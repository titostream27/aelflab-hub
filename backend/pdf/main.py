#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AelfLab PDF Editor Backend — Full API (v2.0)
Author: Tito Ahmad Sugiarto | License: MIT
"""

import json, logging, mimetypes, os, re, sys, time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pdf_editor")

# ── Config ──
BASE_DIR = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = BASE_DIR / "data" / "uploads" / "pdfs"
SIGNATURE_DIR = BASE_DIR / "data" / "signatures"
OUTPUT_DIR = BASE_DIR / "data" / "output"
for d in [UPLOAD_DIR, SIGNATURE_DIR, OUTPUT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_MB = 50
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# ── Router ──
router = APIRouter(prefix="/api/pdf", tags=["pdf"])

# ═══════════════ HELPERS ═══════════════

def parse_pages(raw: str, total_pages: int) -> List[int]:
    if not raw or raw.strip() == "":
        return list(range(total_pages))
    pages = set()
    for part in raw.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            for p in range(int(a), int(b) + 1):
                if 1 <= p <= total_pages:
                    pages.add(p - 1)
        else:
            p = int(part)
            if 1 <= p <= total_pages:
                pages.add(p - 1)
    return sorted(pages)

def safe_filename(original: str) -> str:
    name = Path(original).stem
    name = re.sub(r"[^a-zA-Z0-9_\-.]", "_", name)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"{ts}_{name}.pdf"

def is_valid_pdf(content: bytes) -> bool:
    return content[:5] == b"%PDF-"

def is_valid_image(content: bytes) -> bool:
    return content[:8] == b"\x89PNG\r\n\x1a\n" or content[:2] == b"\xff\xd8"

def b64_to_image_bytes(b64_str: str) -> Optional[bytes]:
    try:
        import base64
        m = re.match(r"data:image/(png|jpeg|jpg);base64,(.+)", b64_str, re.I)
        return base64.b64decode(m.group(2)) if m else None
    except:
        return None

def _find_file(filename: str) -> Optional[Path]:
    p = UPLOAD_DIR / filename
    if p.exists():
        return p
    candidates = list(UPLOAD_DIR.glob(f"*_{filename}"))
    return candidates[0] if candidates else None

# ═══════════════ ENDPOINTS ═══════════════

@router.get("")
async def health():
    return {"status": "ok", "service": "pdf-editor", "version": "2.0"}

@router.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    t0 = time.time()
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Hanya file PDF")
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"Max {MAX_UPLOAD_MB}MB")
    if not is_valid_pdf(content):
        raise HTTPException(400, "Bukan PDF valid")
    out_path = UPLOAD_DIR / safe_filename(file.filename)
    out_path.write_bytes(content)
    pages = 0
    try:
        from PyPDF2 import PdfReader
        pages = len(PdfReader(BytesIO(content)).pages)
    except:
        try:
            import pdfplumber as pp
            with pp.open(BytesIO(content)) as pdf:
                pages = len(pdf.pages)
        except:
            pass
    elapsed = round(time.time() - t0, 2)
    return {"status": "ok", "filename": file.filename, "save_name": out_path.name, "pages": pages, "size": len(content), "load_time_sec": elapsed}

@router.get("/list")
async def list_files():
    files = []
    for p in sorted(UPLOAD_DIR.glob("*.pdf"), key=lambda x: x.stat().st_mtime, reverse=True):
        files.append({"name": p.name, "filename": p.name, "size": p.stat().st_size, "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat()})
    return {"files": files, "count": len(files)}

@router.post("/merge")
async def merge_pdfs(files: str = Form(...), output_name: str = Form("merged.pdf")):
    try:
        flist = json.loads(files)
    except:
        raise HTTPException(400, "Format daftar file tidak valid")
    if len(flist) < 2:
        raise HTTPException(400, "Minimal 2 file")
    from PyPDF2 import PdfMerger
    merger = PdfMerger()
    total = 0
    for fn in flist:
        fp = _find_file(fn)
        if not fp:
            return {"status": "error", "message": f"File tidak ditemukan: {fn}"}
        merger.append(str(fp))
        try:
            from PyPDF2 import PdfReader
            total += len(PdfReader(str(fp)).pages)
        except:
            pass
    oname = safe_filename(output_name)
    opath = OUTPUT_DIR / oname
    merger.write(str(opath))
    merger.close()
    return {"status": "ok", "filename": oname, "pages": total}

@router.post("/split")
async def split_pdf(filename: str = Form(...), pages: str = Form("")):
    fp = _find_file(filename)
    if not fp:
        raise HTTPException(404, f"File tidak ditemukan: {filename}")
    from PyPDF2 import PdfReader, PdfWriter
    reader = PdfReader(str(fp))
    total = len(reader.pages)
    idxs = parse_pages(pages, total)
    writer = PdfWriter()
    for i in idxs:
        writer.add_page(reader.pages[i])
    oname = safe_filename(f"split_{filename}")
    opath = OUTPUT_DIR / oname
    with open(opath, "wb") as f:
        writer.write(f)
    return {"status": "ok", "filename": oname, "pages": len(idxs)}

@router.post("/extract-text")
async def extract_text(filename: str = Form(...)):
    fp = _find_file(filename)
    if not fp:
        raise HTTPException(404, f"File tidak ditemukan: {filename}")
    parts = []
    total = 0
    try:
        import pdfplumber as pp
        with pp.open(str(fp)) as pdf:
            total = len(pdf.pages)
            for pg in pdf.pages:
                t = pg.extract_text()
                if t:
                    parts.append(t)
    except Exception as e:
        log.error(f"pdfplumber: {e}")
        try:
            import fitz
            doc = fitz.open(str(fp))
            total = len(doc)
            for pg in doc:
                t = pg.get_text()
                if t:
                    parts.append(t)
            doc.close()
        except Exception as e2:
            log.error(f"PyMuPDF: {e2}")
            raise HTTPException(500, f"Gagal ekstrak: {e}")
    full = "\n\n".join(parts)
    return {"status": "ok", "pages": total, "text": full, "chars": len(full)}

@router.post("/info")
async def pdf_info(filename: str = Form(...)):
    fp = _find_file(filename)
    if not fp:
        raise HTTPException(404, f"File tidak ditemukan: {filename}")
    from PyPDF2 import PdfReader
    reader = PdfReader(str(fp))
    meta = reader.metadata or {}
    return {"status": "ok", "info": {
        "filename": filename,
        "pages": len(reader.pages),
        "size": fp.stat().st_size,
        "metadata": {
            "title": getattr(meta, "title", None) or None,
            "author": getattr(meta, "author", None) or None,
            "subject": getattr(meta, "subject", None) or None,
            "creator": getattr(meta, "creator", None) or None,
            "producer": getattr(meta, "producer", None) or None,
        }
    }}

@router.post("/upload-signature")
async def upload_signature(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith((".png", ".jpg", ".jpeg")):
        raise HTTPException(400, "Hanya PNG/JPG")
    content = await file.read()
    if not is_valid_image(content):
        raise HTTPException(400, "File gambar corrupt")
    ext = Path(file.filename).suffix.lower()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    sname = f"sig_{ts}{ext}"
    (SIGNATURE_DIR / sname).write_bytes(content)
    return {"status": "ok", "filename": sname, "original": file.filename}

@router.post("/sign")
async def sign_pdf(
    filename: str = Form(...), page: int = Form(0),
    x: float = Form(100), y: float = Form(100),
    sig_name: str = Form(""), sig_scale: float = Form(1.0), sig_opacity: float = Form(0.9),
):
    fp = _find_file(filename)
    if not fp:
        raise HTTPException(404, f"File tidak ditemukan: {filename}")
    sigs = sorted(SIGNATURE_DIR.glob("sig_*"), key=lambda x: x.stat().st_mtime, reverse=True)
    sp = SIGNATURE_DIR / sig_name if sig_name else (sigs[0] if sigs else None)
    if not sp or not sp.exists():
        raise HTTPException(400, "Upload signature dulu")
    try:
        import fitz
        doc = fitz.open(str(fp))
        pc = len(doc)
        page = max(0, min(page, pc - 1))
        target = doc[page]
        r = fitz.Rect(x, y, x + 150 * sig_scale, y + 60 * sig_scale)
        target.insert_image(r, filename=str(sp), keep_proportion=True, overlay=True)
        oname = safe_filename(f"signed_{filename}")
        opath = OUTPUT_DIR / oname
        doc.save(str(opath))
        doc.close()
        return {"status": "ok", "filename": oname, "pages": pc}
    except Exception as e:
        log.error(f"Sign: {e}")
        raise HTTPException(500, f"Gagal sign: {e}")

@router.post("/censor")
async def censor_pdf(filename: str = Form(...), text: str = Form(""), blocks: str = Form("")):
    """Censor by keyword text OR by coordinate blocks (JSON: [{\"page\":0,\"x\":100,\"y\":200,\"w\":150,\"h\":30}])."""
    fp = _find_file(filename)
    if not fp:
        raise HTTPException(404, f"File tidak ditemukan: {filename}")
    try:
        import fitz
        doc = fitz.open(str(fp))
        found = 0

        # Text-based censoring
        if text.strip():
            keywords = [kw.strip() for kw in re.split(r"[,;\n]+", text) if kw.strip()]
            for page_obj in doc:
                for kw in keywords:
                    areas = page_obj.search_for(kw, quads=False)
                    for area in areas:
                        page_obj.add_redact_annot(area, fill=(0, 0, 0), text="")
                        found += 1

        # Block-based censoring (drag-drawn rectangles)
        if blocks.strip():
            try:
                block_list = json.loads(blocks)
            except:
                raise HTTPException(400, "Format blocks tidak valid")
            for blk in block_list:
                pg = max(0, min(blk.get("page", 0), len(doc) - 1))
                x, y, w, h = blk.get("x", 0), blk.get("y", 0), blk.get("w", 100), blk.get("h", 30)
                page_obj = doc[pg]
                rect = fitz.Rect(x, y, x + w, y + h)
                page_obj.add_redact_annot(rect, fill=(0, 0, 0), text="")
                found += 1

        for page_obj in doc:
            page_obj.apply_redactions()

        if found > 0 or blocks.strip():
            oname = safe_filename(f"censored_{filename}")
            opath = OUTPUT_DIR / oname
            doc.save(str(opath))
            doc.close()
            return {"status": "ok", "found": found, "filename": oname, "pages": len(doc) if not doc.is_closed else "?"}
        doc.close()
        return {"status": "ok", "found": 0, "message": "Teks tidak ditemukan"}
    except Exception as e:
        log.error(f"Censor: {e}")
        raise HTTPException(500, f"Gagal: {e}")

@router.post("/watermark")
async def watermark_pdf(
    filename: str = Form(...), watermark_text: str = Form(""),
    watermark_image: str = Form(""), opacity: float = Form(0.3),
    font_size: int = Form(40), angle: float = Form(45),
):
    fp = _find_file(filename)
    if not fp:
        raise HTTPException(404, f"File tidak ditemukan: {filename}")
    try:
        import fitz
        doc = fitz.open(str(fp))
        for pg in doc:
            w, h = pg.rect.width, pg.rect.height
            if watermark_image:
                ib = b64_to_image_bytes(watermark_image)
                if ib:
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                        tf.write(ib)
                        tp = tf.name
                    try:
                        r = fitz.Rect(w * 0.3, h * 0.3, w * 0.7, h * 0.7)
                        pg.insert_image(r, filename=tp, keep_proportion=True, overlay=True, opacity=opacity)
                    finally:
                        os.unlink(tp)
            if watermark_text:
                pt = fitz.Point(w / 2, h / 2)
                pg.insert_text(pt, watermark_text, fontname="helv", fontsize=font_size, color=(0, 0, 0), opacity=opacity, rotate=angle)
        oname = safe_filename(f"watermarked_{filename}")
        opath = OUTPUT_DIR / oname
        doc.save(str(opath))
        doc.close()
        return {"status": "ok", "filename": oname}
    except Exception as e:
        log.error(f"Watermark: {e}")
        raise HTTPException(500, f"Gagal: {e}")

@router.post("/stamp-detect")
async def stamp_detect(filename: str = Form(...)):
    fp = _find_file(filename)
    if not fp:
        raise HTTPException(404, f"File tidak ditemukan: {filename}")
    keywords = ["stempel", "stamp", "cap", "official", "certified", "approved", "segel"]
    results = []
    try:
        import fitz
        doc = fitz.open(str(fp))
        total = len(doc)
        for i, pg in enumerate(doc):
            pt = pg.get_text().lower()
            found = [kw for kw in keywords if kw in pt]
            if found:
                results.append({"page": i + 1, "keywords": found, "confidence": "text_match"})
            for img in pg.get_images(full=True):
                bi = doc.extract_image(img[0])
                nm = bi.get("name", "")
                if any(k in nm.lower() for k in keywords):
                    results.append({"page": i + 1, "image": nm, "confidence": "image_name_match"})
        doc.close()
        return {"status": "ok", "total_pages": total, "hits": len(results), "results": results}
    except Exception as e:
        log.error(f"Stamp: {e}")
        raise HTTPException(500, f"Gagal: {e}")

@router.delete("/file/{filename}")
async def delete_file(filename: str):
    """Delete uploaded PDF file."""
    fp = _find_file(filename)
    if not fp:
        raise HTTPException(404, f"File tidak ditemukan: {filename}")
    try:
        fp.unlink()
        # Also clean up related output files
        for out in OUTPUT_DIR.glob(f"*_{filename}*"):
            try: out.unlink()
            except: pass
        return {"status": "ok", "message": f"{filename} dihapus"}
    except Exception as e:
        raise HTTPException(500, f"Gagal hapus: {e}")

@router.get("/preview/{filename}")
async def preview_page(filename: str, page: int = 0):
    """Render PDF page as PNG image for preview."""
    fp = _find_file(filename)
    if not fp and "." not in filename:
        fp = OUTPUT_DIR / filename
    if not fp or not fp.exists():
        raise HTTPException(404, f"File tidak ditemukan: {filename}")
    try:
        import fitz
        doc = fitz.open(str(fp))
        total = len(doc)
        page = max(0, min(page, total - 1))
        pix = doc[page].get_pixmap(dpi=150)
        doc.close()
        return Response(content=pix.tobytes("png"), media_type="image/png")
    except Exception as e:
        log.error(f"Preview error: {e}")
        raise HTTPException(500, f"Gagal render: {e}")

@router.get("/download/{filename}")
async def download_file(filename: str):
    fp = OUTPUT_DIR / filename
    if not fp.exists():
        raise HTTPException(404, "File tidak ditemukan")
    return FileResponse(str(fp), media_type="application/pdf", filename=filename)
