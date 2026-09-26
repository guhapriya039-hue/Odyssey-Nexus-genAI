"""Multimodal ingestion: text, PDF, DOCX, PPTX, images/OCR, web, audio/video."""

from __future__ import annotations

import csv
import io
import ipaddress
import json
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..config import get_settings
from .textutils import normalise_whitespace, strip_repeated_chars, word_count

SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv", ".json", ".yaml", ".yml",
    ".pdf", ".docx", ".pptx", ".html", ".htm",
    ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp",
    ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac",
    ".mp4", ".mov", ".mkv", ".webm", ".avi",
    ".srt", ".vtt",
}

MAX_TEXT_CHARS = 2_000_000


class IngestionError(RuntimeError):
    pass


@dataclass
class IngestedContent:
    text: str
    kind: str
    title: str
    media_type: str
    meta: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Plain text family
# ---------------------------------------------------------------------------


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _from_plain(data: bytes, filename: str) -> str:
    text = _decode(data)
    suffix = Path(filename).suffix.lower()
    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        rows = [" | ".join(cell.strip() for cell in row) for row in reader if any(row)]
        return "\n".join(rows)
    if suffix == ".json":
        try:
            return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            return text
    if suffix in {".html", ".htm"}:
        from bs4 import BeautifulSoup  # local import: optional dependency

        return BeautifulSoup(text, "html.parser").get_text("\n")
    return text


# ---------------------------------------------------------------------------
# PDF / DOCX / PPTX
# ---------------------------------------------------------------------------


def _from_pdf(data: bytes) -> tuple[str, dict[str, Any]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise IngestionError("pypdf is not installed; PDF ingestion unavailable") from exc

    reader = PdfReader(io.BytesIO(data))
    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception as exc:
            raise IngestionError("PDF is encrypted and cannot be read") from exc

    pages: list[str] = []
    empty_pages = 0
    for index, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        page_text = page_text.strip()
        if not page_text:
            empty_pages += 1
        pages.append(f"[page {index}]\n{page_text}" if page_text else f"[page {index}] (no extractable text)")

    meta: dict[str, Any] = {"pages": len(reader.pages), "empty_pages": empty_pages}
    try:
        info = reader.metadata or {}
        meta["pdf_metadata"] = {
            k: str(v) for k, v in info.items() if isinstance(k, str) and v is not None
        }
    except Exception:
        pass

    body = "\n\n".join(pages)
    if empty_pages and len(body.strip()) < 120 * max(1, empty_pages):
        ocr_text, ocr_meta = _ocr_pdf(data, empty_pages)
        if ocr_text.strip():
            body = f"{body}\n\n[OCR fallback for image-based pages]\n{ocr_text}"
            meta.update(ocr_meta)
            meta["ocr_applied"] = True
    return body, meta


def _ocr_pdf(data: bytes, page_budget: int) -> tuple[str, dict[str, Any]]:
    settings = get_settings()
    if not settings.ocr_enabled:
        return "", {"ocr_attempted": False, "ocr_reason": "ocr_disabled"}
    try:
        import pypdf  # noqa: F401
        from pdf2image import convert_from_bytes  # type: ignore
    except ImportError:
        return "", {"ocr_attempted": False, "ocr_reason": "pdf2image_not_installed"}
    try:
        images = convert_from_bytes(data, first_page=1, last_page=min(page_budget, 10), dpi=200)
    except Exception as exc:
        return "", {"ocr_attempted": True, "ocr_reason": f"rasterise_failed: {exc}"}
    texts = [_ocr_image(img) for img in images]
    joined = "\n\n".join(t for t in texts if t.strip())
    return joined, {"ocr_attempted": True, "ocr_pages": len(texts)}


def _from_docx(data: bytes) -> tuple[str, dict[str, Any]]:
    try:
        import docx  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise IngestionError("python-docx is not installed; DOCX ingestion unavailable") from exc

    document = docx.Document(io.BytesIO(data))
    blocks: list[str] = [p.text.strip() for p in document.paragraphs if p.text.strip()]

    table_count = 0
    for table in document.tables:
        table_count += 1
        rows = [" | ".join(cell.text.strip() for cell in row.cells) for row in table.rows]
        rows = [r for r in rows if r.strip(" |")]
        if rows:
            blocks.append(f"[table {table_count}]\n" + "\n".join(rows))

    core = document.core_properties
    meta = {
        "paragraphs": len(document.paragraphs),
        "tables": table_count,
        "docx_metadata": {
            "title": core.title or "",
            "author": core.author or "",
            "created": str(core.created) if core.created else "",
            "modified": str(core.modified) if core.modified else "",
        },
    }
    return "\n\n".join(blocks), meta


def _from_pptx(data: bytes) -> tuple[str, dict[str, Any]]:
    try:
        from pptx import Presentation  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise IngestionError("python-pptx is not installed; PPTX ingestion unavailable") from exc

    presentation = Presentation(io.BytesIO(data))
    slides: list[str] = []
    for index, slide in enumerate(presentation.slides, start=1):
        texts: list[str] = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                value = shape.text_frame.text.strip()
                if value:
                    texts.append(value)
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    texts.append(" | ".join(cell.text.strip() for cell in row.cells))
        slides.append(f"[slide {index}]\n" + ("\n".join(texts) if texts else "(empty slide)"))
    return "\n\n".join(slides), {"slides": len(presentation.slides)}


# ---------------------------------------------------------------------------
# Images / OCR
# ---------------------------------------------------------------------------


def _ocr_image(image: Any) -> str:
    try:
        import pytesseract
    except ImportError:
        return ""
    try:
        return pytesseract.image_to_string(image)
    except Exception:
        return ""


def _from_image(data: bytes) -> tuple[str, dict[str, Any]]:
    settings = get_settings()
    meta: dict[str, Any] = {"ocr_attempted": False}
    if not settings.ocr_enabled:
        meta["ocr_reason"] = "ocr_disabled"
        return "", meta
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover
        raise IngestionError("Pillow is not installed; image ingestion unavailable") from exc

    try:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image)
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        meta.update({"width": image.width, "height": image.height, "format": image.format})
    except Exception as exc:
        raise IngestionError(f"Unreadable image: {exc}") from exc

    meta["ocr_attempted"] = True
    text = _ocr_image(image)
    if not text.strip():
        meta["ocr_reason"] = "no_text_returned"
    return text, meta


# ---------------------------------------------------------------------------
# Audio / video
# ---------------------------------------------------------------------------


def _from_media(data: bytes, filename: str) -> tuple[str, dict[str, Any]]:
    suffix = Path(filename).suffix.lower()
    if suffix in {".srt", ".vtt"}:
        return _from_subtitles(_decode(data)), {"transcription": "subtitle_sidecar"}

    settings = get_settings()
    if not settings.speech_to_text_enabled:
        return "", {
            "transcription": "disabled",
            "hint": "Set SPEECH_TO_TEXT_ENABLED=true and install faster-whisper to enable audio/video.",
        }

    tmp_path = Path(settings.upload_dir) / f"_stt_{abs(hash(filename))}{suffix}"
    try:
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_bytes(data)
        from faster_whisper import WhisperModel  # type: ignore

        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, info = model.transcribe(str(tmp_path), beam_size=5, vad_filter=True)
        lines = [f"[{s.start:07.2f} --> {s.end:07.2f}] {s.text.strip()}" for s in segments]
        return "\n".join(lines), {
            "transcription": "faster_whisper",
            "language": getattr(info, "language", ""),
            "duration_seconds": round(float(getattr(info, "duration", 0.0)), 2),
        }
    except ImportError:
        return "", {
            "transcription": "unavailable",
            "hint": "Install faster-whisper for audio/video, or upload a .srt/.vtt sidecar.",
        }
    except Exception as exc:
        return "", {"transcription": "failed", "error": str(exc)[:300]}
    finally:
        tmp_path.unlink(missing_ok=True)


def _from_subtitles(text: str) -> str:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.isdigit() or "-->" in line or line.upper().startswith("WEBVTT"):
            continue
        line = re.sub(r"<[^>]+>", "", line)
        if line:
            lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Web
# ---------------------------------------------------------------------------

_PRIVATE_HOSTS = re.compile(
    r"^(?:localhost|127\.|10\.|192\.168\.|169\.254\.|0\.|172\.(?:1[6-9]|2\d|3[01])\.|\[?::1\]?$)",
    re.IGNORECASE,
)


def _resolve_addresses(host: str) -> list[Any]:
    """Every IP address the host resolves to."""
    import socket

    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise IngestionError(f"Cannot resolve host '{host}'") from exc

    addresses: list[Any] = []
    for info in infos:
        try:
            addresses.append(ipaddress.ip_address(info[4][0]))
        except ValueError:  # pragma: no cover - non-IP sockaddr
            continue
    return addresses


def _is_internal_address(address: Any) -> bool:
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _assert_public_url(url: str, allow_private: bool) -> None:
    """Reject anything that is not a public web host.

    A string check alone is not enough: `metadata.internal` or a decimal-encoded
    address sails past a pattern match while still resolving to a private or
    link-local address. So the hostname is resolved and every answer is checked,
    which also covers a name that points at the cloud metadata endpoint.

    Note the residual DNS-rebinding window: the fetch resolves again after this
    check. Closing it entirely needs a pinned-IP transport, which is out of scope
    for the prototype; ALLOW_PRIVATE_NETWORK_FETCH stays the hard switch.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise IngestionError("Only http and https URLs are supported")
    host = parsed.hostname or ""
    if not host:
        raise IngestionError("URL has no host")
    if allow_private:
        return

    blocked = (
        "Refusing to fetch a private or loopback address (SSRF protection). "
        "Set ALLOW_PRIVATE_NETWORK_FETCH=true to override in a trusted network."
    )
    if _PRIVATE_HOSTS.match(host):
        raise IngestionError(blocked)

    # An IP literal needs no resolution, but the same classification applies.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _is_internal_address(literal):
            raise IngestionError(blocked)
        return

    for address in _resolve_addresses(host):
        if _is_internal_address(address):
            raise IngestionError(blocked)


def _from_web(url: str) -> tuple[str, dict[str, Any]]:
    settings = get_settings()
    if not settings.allow_web_ingestion:
        raise IngestionError("Web ingestion is disabled (ALLOW_WEB_INGESTION=false)")

    _assert_public_url(url, settings.allow_private_network_fetch)

    import httpx
    from bs4 import BeautifulSoup

    headers = {"User-Agent": "OdysseyTransformCore/1.4 (+source-ingestion)"}
    try:
        with httpx.Client(follow_redirects=True, timeout=25.0, headers=headers) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise IngestionError(f"Source returned HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise IngestionError(f"Could not fetch source: {exc}") from exc

    content_type = response.headers.get("content-type", "")
    if "pdf" in content_type.lower():
        text, meta = _from_pdf(response.content)
        meta["content_type"] = content_type
        return text, meta

    soup = BeautifulSoup(response.text, "html.parser")
    for element in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form"]):
        element.decompose()

    title = (soup.title.string.strip() if soup.title and soup.title.string else "") or url
    main = soup.find("main") or soup.find("article") or soup.body or soup
    blocks = [
        line.strip()
        for line in main.get_text("\n").splitlines()
        if line.strip() and len(line.strip()) > 1
    ]

    meta = {
        "url": str(response.url),
        "status_code": response.status_code,
        "content_type": content_type,
        "http_title": title,
        "links": len(soup.find_all("a")),
    }
    if soup.find("table"):
        meta["tables_detected"] = len(soup.find_all("table"))
    return "\n".join(blocks), meta


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def ingest_bytes(
    data: bytes,
    filename: str,
    media_type: str | None = None,
    declared_title: str | None = None,
) -> IngestedContent:
    if not data:
        raise IngestionError("Uploaded file is empty")

    settings = get_settings()
    if len(data) > settings.max_upload_bytes:
        raise IngestionError(
            f"File exceeds the {settings.max_upload_bytes // (1024 * 1024)} MB limit"
        )

    suffix = Path(filename).suffix.lower()
    guessed = media_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    title = (declared_title or Path(filename).stem or "Untitled source").strip()
    meta: dict[str, Any] = {"filename": filename, "declared_media_type": guessed, "suffix": suffix}
    warnings: list[str] = []

    if suffix in {".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv", ".json",
                  ".yaml", ".yml", ".html", ".htm"} or guessed.startswith("text/"):
        text, kind = _from_plain(data, filename), "text"
    elif suffix == ".pdf" or "pdf" in guessed:
        text, extra = _from_pdf(data)
        kind = "pdf"
        meta.update(extra)
    elif suffix == ".docx" or "wordprocessingml" in guessed:
        text, extra = _from_docx(data)
        kind = "docx"
        meta.update(extra)
    elif suffix == ".pptx" or "presentationml" in guessed:
        text, extra = _from_pptx(data)
        kind = "pptx"
        meta.update(extra)
    elif suffix in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"} or guessed.startswith("image/"):
        text, extra = _from_image(data)
        kind = "image"
        meta.update(extra)
        if not text.strip():
            warnings.append(
                "No text recognised in the image. Install Tesseract OCR and verify the image quality."
            )
    elif suffix in {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".mp4", ".mov",
                    ".mkv", ".webm", ".avi", ".srt", ".vtt"} or guessed.startswith(("audio/", "video/")):
        text, extra = _from_media(data, filename)
        kind = "audio" if guessed.startswith("audio/") or suffix in {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".srt"} else "video"
        meta.update(extra)
        if not text.strip():
            warnings.append(str(extra.get("hint") or "No transcript produced for this media file."))
    else:
        raise IngestionError(
            f"Unsupported source type '{suffix or guessed}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    text = normalise_whitespace(strip_repeated_chars(text))
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
        warnings.append(f"Source truncated to {MAX_TEXT_CHARS:,} characters for processing.")

    if not text.strip():
        raise IngestionError(
            "No readable text could be extracted. If this is a scan, enable OCR; "
            "if it is media, enable speech-to-text or upload a subtitle sidecar."
        )

    meta["word_count"] = word_count(text)
    meta["char_count"] = len(text)
    return IngestedContent(
        text=text,
        kind=kind,
        title=title[:500],
        media_type=guessed,
        meta=meta,
        warnings=warnings,
    )


def ingest_url(url: str, declared_title: str = "") -> IngestedContent:
    text, meta = _from_web(url)
    text = normalise_whitespace(strip_repeated_chars(text))
    if not text.strip():
        raise IngestionError("The page had no extractable readable text")
    title = declared_title.strip() or meta.get("http_title") or url
    return IngestedContent(
        text=text,
        kind="web",
        title=title[:500],
        media_type="text/html",
        meta={**meta, "word_count": word_count(text), "char_count": len(text)},
    )
