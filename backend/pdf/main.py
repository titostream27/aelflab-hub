#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AelfLab PDF Editor Backend — Full API (v2.1)
Author: Tito Ahmad Sugiarto | License: MIT

Coordinate contract (v2.1)
--------------------------
All geometry accepted by this API (sign x/y/w/h, censor blocks) is in
**PDF points** (72 per inch), origin top-left — identical to PyMuPDF's
page space.

Previews are rendered at ``dpi = 72 * zoom``, so:

    canvas_pixels = points * zoom

The client is responsible for dividing canvas pixels by ``zoom`` before
sending coordinates back. Every preview response carries the values needed
for that conversion in its ``X-Pdf-*`` headers.
"""

import json, logging, os, re, time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple

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

# Preview render limits
MIN_ZOOM = 0.05
MAX_ZOOM = 4.0
MAX_PREVIEW_PIXELS = 4000  # cap on the longest rendered edge

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
    except Exception:
        return None

def _sanitize_name(filename: str) -> str:
    """Reject any path component. Filenames are flat names, never paths."""
    if not filename or not filename.strip():
        raise HTTPException(400, "Nama file kosong")
    name = filename.strip()
    if "/" in name or "\\" in name or "\x00" in name or ".." in name or name.startswith("."):
        raise HTTPException(400, "Nama file tidak valid")
    if name != os.path.basename(name):
        raise HTTPException(400, "Nama file tidak valid")
    return name

def _resolve_file(filename: str, include_output: bool = True) -> Optional[Path]:
    """Locate a PDF in uploads or output.

    Output files are searchable too, so results can be chained (sign a merged
    file, censor a signed file, preview any result).
    """
    name = _sanitize_name(filename)
    search_dirs = [UPLOAD_DIR] + ([OUTPUT_DIR] if include_output else [])
    for d in search_dirs:
        p = d / name
        if p.exists() and p.is_file():
            return p
    # Fallback: original upload name without the timestamp prefix
    for d in search_dirs:
        candidates = sorted(d.glob(f"*_{name}"), key=lambda x: x.stat().st_mtime, reverse=True)
        if candidates:
            return candidates[0]
    return None

def _require_file(filename: str, include_output: bool = True) -> Path:
    fp = _resolve_file(filename, include_output)
    if not fp:
        raise HTTPException(404, f"File tidak ditemukan: {filename}")
    return fp

def _find_file(filename: str) -> Optional[Path]:
    """Backwards-compatible alias."""
    return _resolve_file(filename)

def _page_geometry(doc) -> List[dict]:
    """Per-page size in PDF points, as displayed (rotation applied)."""
    out = []
    for i, pg in enumerate(doc):
        r = pg.rect  # already reflects /Rotate
        out.append({
            "page": i,
            "width_pt": round(r.width, 2),
            "height_pt": round(r.height, 2),
            "rotation": pg.rotation,
        })
    return out

def _clamp_zoom(zoom: float, width_pt: float, height_pt: float) -> float:
    zoom = max(MIN_ZOOM, min(float(zoom), MAX_ZOOM))
    longest = max(width_pt, height_pt) * zoom
    if longest > MAX_PREVIEW_PIXELS:
        zoom = MAX_PREVIEW_PIXELS / max(width_pt, height_pt)
    return zoom

def _pixmap_with_opacity(path: Path, opacity: float):
    """Return a Pixmap with alpha scaled by ``opacity``, or None for full opacity.

    ``Page.insert_image()`` has no opacity parameter, so transparency has to be
    baked into the image's alpha channel. Any existing transparency (e.g. a
    signature PNG with a cut-out background) is preserved by multiplying rather
    than replacing the alpha values.
    """
    import fitz
    if opacity >= 0.99:
        return None
    pix = fitz.Pixmap(str(path))
    if not pix.alpha:
        pix = fitz.Pixmap(pix, 1)  # add an opaque alpha channel
    n = pix.n
    data = pix.samples
    count = pix.width * pix.height
    alpha = bytes(int(data[i * n + n - 1] * opacity) for i in range(count))
    pix.set_alpha(alpha, premultiply=0)
    return pix

def _clamp_rect(doc_page, x: float, y: float, w: float, h: float) -> Optional["object"]:
    """Build a rect clamped to the page, or None if it collapses."""
    import fitz
    pr = doc_page.rect
    x0 = max(pr.x0, min(float(x), pr.x1))
    y0 = max(pr.y0, min(float(y), pr.y1))
    x1 = max(pr.x0, min(float(x) + float(w), pr.x1))
    y1 = max(pr.y0, min(float(y) + float(h), pr.y1))
    if x1 - x0 < 1 or y1 - y0 < 1:
        return None
    return fitz.Rect(x0, y0, x1, y1)

# ═══════════════ ENDPOINTS ═══════════════

@router.get("")
async def health():
    return {"status": "ok", "service": "pdf-editor", "version": "2.1"}

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
    except Exception:
        try:
            import pdfplumber as pp
            with pp.open(BytesIO(content)) as pdf:
                pages = len(pdf.pages)
        except Exception:
            pass
    elapsed = round(time.time() - t0, 2)
    return {"status": "ok", "filename": file.filename, "save_name": out_path.name, "pages": pages, "size": len(content), "load_time_sec": elapsed}

@router.get("/list")
async def list_files():
    files = []
    for p in sorted(UPLOAD_DIR.glob("*.pdf"), key=lambda x: x.stat().st_mtime, reverse=True):
        files.append({"name": p.name, "filename": p.name, "size": p.stat().st_size, "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(), "source": "upload"})
    return {"files": files, "count": len(files)}

@router.get("/outputs")
async def list_outputs():
    """Generated results, newest first — so the UI can preview/re-edit them."""
    files = []
    for p in sorted(OUTPUT_DIR.glob("*.pdf"), key=lambda x: x.stat().st_mtime, reverse=True):
        files.append({"name": p.name, "filename": p.name, "size": p.stat().st_size, "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(), "source": "output"})
    return {"files": files, "count": len(files)}

@router.get("/pages/{filename}")
async def page_info(filename: str):
    """Page count and per-page point dimensions.

    The client needs this to size its canvas, bound page navigation, and
    compute a fit-to-width zoom before rendering anything.
    """
    fp = _require_file(filename)
    try:
        import fitz
        doc = fitz.open(str(fp))
        try:
            geo = _page_geometry(doc)
        finally:
            doc.close()
        return {"status": "ok", "filename": fp.name, "total_pages": len(geo), "pages": geo}
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Page info: {e}")
        raise HTTPException(500, f"Gagal baca halaman: {e}")

@router.get("/preview/{filename}")
async def preview_page(filename: str, page: int = 0, zoom: float = 1.0):
    """Render a page as PNG at ``dpi = 72 * zoom``.

    Response headers expose the geometry so the client can convert canvas
    pixels back to PDF points without guessing:
      X-Pdf-Zoom          effective zoom actually used (may be clamped)
      X-Pdf-Page          zero-based page index actually rendered
      X-Pdf-Total-Pages   total pages in the document
      X-Pdf-Width-Pt      page width in points
      X-Pdf-Height-Pt     page height in points
    """
    fp = _require_file(filename)
    try:
        import fitz
        doc = fitz.open(str(fp))
        try:
            total = len(doc)
            if total == 0:
                raise HTTPException(400, "PDF tanpa halaman")
            page = max(0, min(int(page), total - 1))
            target = doc[page]
            w_pt, h_pt = target.rect.width, target.rect.height
            eff_zoom = _clamp_zoom(zoom, w_pt, h_pt)
            pix = target.get_pixmap(matrix=fitz.Matrix(eff_zoom, eff_zoom))
            png = pix.tobytes("png")
        finally:
            doc.close()
        return Response(content=png, media_type="image/png", headers={
            "X-Pdf-Zoom": f"{eff_zoom:.6f}",
            "X-Pdf-Page": str(page),
            "X-Pdf-Total-Pages": str(total),
            "X-Pdf-Width-Pt": f"{w_pt:.2f}",
            "X-Pdf-Height-Pt": f"{h_pt:.2f}",
            "Access-Control-Expose-Headers": "X-Pdf-Zoom,X-Pdf-Page,X-Pdf-Total-Pages,X-Pdf-Width-Pt,X-Pdf-Height-Pt",
            "Cache-Control": "no-store",
        })
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Preview error: {e}")
        raise HTTPException(500, f"Gagal render: {e}")

@router.post("/merge")
async def merge_pdfs(files: str = Form(...), output_name: str = Form("merged.pdf")):
    try:
        flist = json.loads(files)
    except Exception:
        raise HTTPException(400, "Format daftar file tidak valid")
    if len(flist) < 2:
        raise HTTPException(400, "Minimal 2 file")
    from PyPDF2 import PdfMerger
    merger = PdfMerger()
    total = 0
    for fn in flist:
        fp = _resolve_file(fn)
        if not fp:
            return {"status": "error", "message": f"File tidak ditemukan: {fn}"}
        merger.append(str(fp))
        try:
            from PyPDF2 import PdfReader
            total += len(PdfReader(str(fp)).pages)
        except Exception:
            pass
    oname = safe_filename(output_name)
    opath = OUTPUT_DIR / oname
    merger.write(str(opath))
    merger.close()
    return {"status": "ok", "filename": oname, "pages": total}

@router.post("/split")
async def split_pdf(filename: str = Form(...), pages: str = Form("")):
    fp = _require_file(filename)
    from PyPDF2 import PdfReader, PdfWriter
    reader = PdfReader(str(fp))
    total = len(reader.pages)
    idxs = parse_pages(pages, total)
    if not idxs:
        raise HTTPException(400, "Tidak ada halaman yang cocok")
    writer = PdfWriter()
    for i in idxs:
        writer.add_page(reader.pages[i])
    oname = safe_filename(f"split_{fp.name}")
    opath = OUTPUT_DIR / oname
    with open(opath, "wb") as f:
        writer.write(f)
    return {"status": "ok", "filename": oname, "pages": len(idxs)}

@router.post("/extract-text")
async def extract_text(filename: str = Form(...)):
    fp = _require_file(filename)
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
    fp = _require_file(filename)
    from PyPDF2 import PdfReader
    reader = PdfReader(str(fp))
    meta = reader.metadata or {}
    sizes = []
    try:
        import fitz
        doc = fitz.open(str(fp))
        try:
            sizes = _page_geometry(doc)
        finally:
            doc.close()
    except Exception:
        pass
    return {"status": "ok", "info": {
        "filename": fp.name,
        "pages": len(reader.pages),
        "size": fp.stat().st_size,
        "page_sizes": sizes,
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
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    sname = f"sig_{ts}{ext}"
    (SIGNATURE_DIR / sname).write_bytes(content)
    return {"status": "ok", "filename": sname, "original": file.filename}

@router.post("/sign")
async def sign_pdf(
    filename: str = Form(...), page: int = Form(0),
    x: float = Form(100), y: float = Form(100),
    w: float = Form(0), h: float = Form(0),
    sig_name: str = Form(""), sig_scale: float = Form(1.0), sig_opacity: float = Form(0.9),
):
    """Stamp a signature image.

    ``x/y/w/h`` are PDF points, origin top-left — the same space the preview
    reports. If ``w``/``h`` are omitted the legacy 150x60 * sig_scale box is
    used, so older clients keep working.
    """
    fp = _require_file(filename)
    if sig_name:
        sig_name = _sanitize_name(sig_name)
        sp = SIGNATURE_DIR / sig_name
    else:
        sigs = sorted(SIGNATURE_DIR.glob("sig_*"), key=lambda p: p.stat().st_mtime, reverse=True)
        sp = sigs[0] if sigs else None
    if not sp or not sp.exists():
        raise HTTPException(400, "Upload signature dulu")

    box_w = float(w) if w and w > 0 else 150.0 * sig_scale
    box_h = float(h) if h and h > 0 else 60.0 * sig_scale
    opacity = max(0.05, min(float(sig_opacity), 1.0))

    try:
        import fitz
        doc = fitz.open(str(fp))
        try:
            pc = len(doc)
            page = max(0, min(int(page), pc - 1))
            target = doc[page]
            rect = _clamp_rect(target, x, y, box_w, box_h)
            if rect is None:
                raise HTTPException(400, "Posisi signature di luar halaman")
            faded = _pixmap_with_opacity(sp, opacity)
            if faded is not None:
                target.insert_image(rect, pixmap=faded, keep_proportion=True, overlay=True)
            else:
                target.insert_image(rect, filename=str(sp), keep_proportion=True, overlay=True)
            oname = safe_filename(f"signed_{fp.name}")
            opath = OUTPUT_DIR / oname
            doc.save(str(opath))
        finally:
            doc.close()
        return {"status": "ok", "filename": oname, "pages": pc, "page": page,
                "rect": [round(rect.x0, 2), round(rect.y0, 2), round(rect.x1, 2), round(rect.y1, 2)]}
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Sign: {e}")
        raise HTTPException(500, f"Gagal sign: {e}")

@router.post("/censor")
async def censor_pdf(filename: str = Form(...), text: str = Form(""), blocks: str = Form("")):
    """Censor by keyword OR by coordinate blocks.

    Blocks are JSON in PDF points, origin top-left:
      [{"page":0,"x":100,"y":200,"w":150,"h":30}]
    """
    fp = _require_file(filename)
    try:
        import fitz
        doc = fitz.open(str(fp))
        oname = None
        page_count = len(doc)
        try:
            found = 0
            touched = set()

            if text.strip():
                keywords = [kw.strip() for kw in re.split(r"[,;\n]+", text) if kw.strip()]
                for idx, page_obj in enumerate(doc):
                    for kw in keywords:
                        for area in page_obj.search_for(kw, quads=False):
                            page_obj.add_redact_annot(area, fill=(0, 0, 0), text="")
                            found += 1
                            touched.add(idx)

            if blocks.strip():
                try:
                    block_list = json.loads(blocks)
                except Exception:
                    raise HTTPException(400, "Format blocks tidak valid")
                for blk in block_list:
                    pg = max(0, min(int(blk.get("page", 0)), page_count - 1))
                    page_obj = doc[pg]
                    rect = _clamp_rect(page_obj, blk.get("x", 0), blk.get("y", 0), blk.get("w", 100), blk.get("h", 30))
                    if rect is None:
                        continue
                    page_obj.add_redact_annot(rect, fill=(0, 0, 0), text="")
                    found += 1
                    touched.add(pg)

            if found == 0:
                return {"status": "ok", "found": 0, "pages": page_count, "message": "Tidak ada yang disensor"}

            for idx in touched:
                doc[idx].apply_redactions()

            oname = safe_filename(f"censored_{fp.name}")
            doc.save(str(OUTPUT_DIR / oname))
        finally:
            doc.close()
        return {"status": "ok", "found": found, "filename": oname, "pages": page_count}
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Censor: {e}")
        raise HTTPException(500, f"Gagal: {e}")

@router.post("/watermark")
async def watermark_pdf(
    filename: str = Form(...), watermark_text: str = Form(""),
    watermark_image: str = Form(""), opacity: float = Form(0.3),
    font_size: int = Form(40), angle: float = Form(45),
):
    fp = _require_file(filename)
    if not watermark_text.strip() and not watermark_image.strip():
        raise HTTPException(400, "Isi teks atau gambar watermark")
    opacity = max(0.05, min(float(opacity), 1.0))
    try:
        import fitz
        doc = fitz.open(str(fp))
        try:
            font = fitz.Font("helv") if watermark_text.strip() else None
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
                            faded = _pixmap_with_opacity(Path(tp), opacity)
                            if faded is not None:
                                pg.insert_image(r, pixmap=faded, keep_proportion=True, overlay=True)
                            else:
                                pg.insert_image(r, filename=tp, keep_proportion=True, overlay=True)
                        finally:
                            os.unlink(tp)
                if watermark_text:
                    # insert_text() only accepts rotations that are multiples of
                    # 90, so arbitrary angles go through TextWriter + morph.
                    tw = fitz.TextWriter(pg.rect)
                    text_w = font.text_length(watermark_text, fontsize=font_size)
                    origin = fitz.Point((w - text_w) / 2, h / 2 + font_size * 0.35)
                    tw.append(origin, watermark_text, font=font, fontsize=font_size)
                    pivot = fitz.Point(w / 2, h / 2)
                    morph = (pivot, fitz.Matrix(float(angle) % 360))
                    tw.write_text(pg, color=(0, 0, 0), opacity=opacity, morph=morph, overlay=True)
            oname = safe_filename(f"watermarked_{fp.name}")
            doc.save(str(OUTPUT_DIR / oname))
        finally:
            doc.close()
        return {"status": "ok", "filename": oname}
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Watermark: {e}")
        raise HTTPException(500, f"Gagal: {e}")

@router.post("/stamp-detect")
async def stamp_detect(filename: str = Form(...)):
    fp = _require_file(filename)
    keywords = ["stempel", "stamp", "cap", "official", "certified", "approved", "segel"]
    results = []
    try:
        import fitz
        doc = fitz.open(str(fp))
        try:
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
        finally:
            doc.close()
        return {"status": "ok", "total_pages": total, "hits": len(results), "results": results}
    except Exception as e:
        log.error(f"Stamp: {e}")
        raise HTTPException(500, f"Gagal: {e}")

@router.delete("/file/{filename}")
async def delete_file(filename: str):
    """Delete an uploaded PDF (and its derived outputs)."""
    fp = _require_file(filename, include_output=False)
    try:
        stem = fp.name
        fp.unlink()
        for out in OUTPUT_DIR.glob(f"*_{stem}*"):
            try:
                out.unlink()
            except Exception:
                pass
        return {"status": "ok", "message": f"{stem} dihapus"}
    except Exception as e:
        raise HTTPException(500, f"Gagal hapus: {e}")

@router.get("/download/{filename}")
async def download_file(filename: str):
    name = _sanitize_name(filename)
    fp = OUTPUT_DIR / name
    if not fp.exists():
        fp = UPLOAD_DIR / name
    if not fp.exists() or not fp.is_file():
        raise HTTPException(404, "File tidak ditemukan")
    return FileResponse(str(fp), media_type="application/pdf", filename=name)
