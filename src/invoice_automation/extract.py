"""Read invoice pages with Azure AI Document Intelligence (D-003), one page per request (D-004).

Every response is cached on disk, keyed by the source file's content, the page number and the
model. Re-running on the same scan costs nothing, so parsing and matching code can be changed and
re-tested freely; only a new scan uses free-tier pages.
"""

import hashlib
import json
import os
from pathlib import Path

import pymupdf
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv

from .files import save_atomic

CACHE_DIR = Path("data/cache/di")


def split_pages(pdf_path: Path) -> list[bytes]:
    """Return each page of a PDF as its own single-page PDF (D-004)."""
    pages = []
    with pymupdf.open(pdf_path) as doc:
        for i in range(doc.page_count):
            single = pymupdf.open()
            single.insert_pdf(doc, from_page=i, to_page=i)
            pages.append(single.tobytes())
            single.close()
    return pages


def _client() -> DocumentIntelligenceClient:
    load_dotenv()
    endpoint = os.environ.get("AZURE_DI_ENDPOINT")
    key = os.environ.get("AZURE_DI_KEY")
    if not endpoint or not key:
        raise RuntimeError("AZURE_DI_ENDPOINT / AZURE_DI_KEY missing. Copy .env.example to .env and fill them in.")
    return DocumentIntelligenceClient(endpoint, AzureKeyCredential(key))


def analyze_page(pdf_path: Path, page_index: int, model_id: str) -> dict:
    """Analyse one page with the given model and return the raw result as a dict.

    The cache key uses the original file's bytes (not the split page's bytes, which PyMuPDF may
    not reproduce byte-for-byte), so the same scan always hits the cache.
    """
    file_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:16]
    cache_file = CACHE_DIR / model_id / f"{file_hash}_p{page_index + 1}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    page_pdf = split_pages(pdf_path)[page_index]
    poller = _client().begin_analyze_document(model_id, body=page_pdf, content_type="application/pdf")
    result = poller.result().as_dict()

    text = json.dumps(result, ensure_ascii=False, indent=1)
    save_atomic(cache_file, lambda tmp: tmp.write_text(text, encoding="utf-8"))
    return result
