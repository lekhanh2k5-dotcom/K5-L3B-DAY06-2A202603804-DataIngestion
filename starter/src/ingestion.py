"""Read and normalize source PDFs into DocumentPage objects (one per physical page).

Choices (documented in the report):
  - Extractor: PyMuPDF. pypdf was tried first but inserts spaces inside Vietnamese
    words ("ngư ời", "đư ờng"); PyMuPDF extracts these pages cleanly.
  - Each physical page keeps document_id, source, page number and a quality status.
    Empty or garbled pages are recorded with a reason, never silently dropped.
  - Normalization keeps legal structure: wrapped lines are re-joined into paragraphs,
    but every Chương / Điều / khoản (1.) / điểm (a)) starts a new line.
  - Running headers (Công báo line, page number) are removed; amendment footnotes are
    moved out of the body text into metadata["footnotes"] together with their markers.
"""
import re
import unicodedata
from pathlib import Path

import pymupdf

from .models import DocumentPage

MIN_CHARS = 200
VI_DIACRITIC = re.compile(r'[ăâđêôơưàáạảãằắặẳẵầấậẩẫèéẹẻẽềếệểễìíịỉĩòóọỏõồốộổỗờớợởỡùúụủũừứựửữỳýỵỷỹ]', re.I)

HEADER_LINE = re.compile(r'^\s*(\d{1,3}\s+)?CÔNG BÁO/Số[^\n]*$', re.M)
PAGE_NUMBER = re.compile(r'^\s*\d{1,3}\s*$')
FOOTNOTE_START = re.compile(
    r'^(\d{1,3})\s+(Khoản|Điểm|Điều|Cụm từ|Chương|Mục|Tên|Đoạn|Từ|Các|Luật|Nội dung|Bổ sung|Thay)\b')
NEW_PARAGRAPH = re.compile(
    r'^(Chương\s+[IVXLC]+\b|Điều\s+\d+[a-z]?\.|\d+[a-z]?\.\s|\d+[a-z]?\.\d{1,3}\s|[a-zđ]\)\s|[A-ZĐ]\)\s)'
    r'|^[A-ZĐÀ-Ỹ ,;-]{8,}$')   # all-caps chapter titles


def _strip_running_header(lines: list[str]) -> list[str]:
    lines = [l for l in lines if not HEADER_LINE.match(l)]
    # page number: standalone number among the first non-empty lines (or the last line)
    head = [i for i, l in enumerate(lines) if l.strip()][:2]
    for i in head:
        if PAGE_NUMBER.match(lines[i]):
            lines[i] = ''
    return lines


def _split_footnotes(lines: list[str]) -> tuple[list[str], list[dict]]:
    """Footnotes sit at the bottom of the page; find the first footnote line after which
    every remaining non-empty line belongs to the footnote block."""
    starts = [i for i, l in enumerate(lines) if FOOTNOTE_START.match(l.strip())]
    if not starts:
        return lines, []
    # footnote block must be in the lower part of the page and contiguous to the end
    first = next((i for i in starts if i >= len(lines) * 0.4), None)
    if first is None:
        return lines, []
    notes, cur = [], None
    for l in lines[first:]:
        m = FOOTNOTE_START.match(l.strip())
        if m:
            cur = {'marker': m.group(1), 'text': l.strip()[len(m.group(1)):].strip()}
            notes.append(cur)
        elif l.strip() and cur:
            cur['text'] += ' ' + l.strip()
    body = lines[:first]
    while body and (not body[-1].strip() or set(body[-1].strip()) <= set('_-—')):
        body.pop()
    return body, notes


def _remove_footnote_markers(text: str, markers: set[str]) -> str:
    for mk in sorted(markers, key=len, reverse=True):
        # clause number followed by footnote marker: "3.8 Khi chở" -> "3. Khi chở"
        text = re.sub(rf'^(\d+[a-z]?)\.{mk}(\s)', r'\1.\2', text, flags=re.M)
        # marker glued to a word/heading: "Bộ Xây dựng37 quy định" -> "Bộ Xây dựng quy định"
        text = re.sub(rf'(?<!QH)(?<!cm)(?<!kW)(?<=[^\W\d_]){mk}(?=[\s,.;:)]|$)', '', text, flags=re.M)
    return text


def normalize_text(text: str) -> str:
    """NFC, unify whitespace, re-join wrapped lines into paragraphs; keep structural breaks."""
    text = unicodedata.normalize('NFC', text)
    text = text.replace(' ', ' ').replace('​', '').replace('\t', ' ')
    text = re.sub(r'(\w)-\s*\n\s*(\w)', r'\1-\2', text)          # "xi -\nlanh" style breaks
    text = re.sub(r'\s+-(?=lanh)', '-', text)                      # "xi -lanh" -> "xi-lanh"
    paragraphs: list[str] = []
    for raw in text.split('\n'):
        line = re.sub(r'[ ]{2,}', ' ', raw).strip()
        if not line:
            continue
        if not paragraphs or NEW_PARAGRAPH.match(line):
            paragraphs.append(line)
        else:
            paragraphs[-1] += ' ' + line
    return '\n'.join(paragraphs)


def page_quality(text: str) -> str | None:
    """Return None if usable, otherwise a reason string."""
    if len(text) < MIN_CHARS:
        return f'empty_or_short (<{MIN_CHARS} chars)'
    letters = sum(ch.isalpha() for ch in text)
    if letters and len(VI_DIACRITIC.findall(text)) / letters < 0.05:
        return 'garbled_extraction (Vietnamese diacritics missing / wrong glyphs)'
    return None


def load_pdf(path: Path, document_id: str, source: str,
             metadata: dict | None = None) -> list[DocumentPage]:
    """Extract every physical page; keep page number, source and quality status."""
    pages = []
    with pymupdf.open(path) as doc:
        for no, page in enumerate(doc, 1):
            lines = page.get_text().split('\n')
            lines = _strip_running_header(lines)
            body, notes = _split_footnotes(lines)
            text = normalize_text('\n'.join(body))
            text = _remove_footnote_markers(text, {n['marker'] for n in notes})
            meta = dict(metadata or {})
            meta['footnotes'] = notes
            meta['quality_issue'] = page_quality(text)
            pages.append(DocumentPage(document_id=document_id, source=source, page=no,
                                      text=text, metadata=meta))
    return pages


def load_corpus(root: Path, manifest: dict) -> tuple[list[DocumentPage], list[dict]]:
    """Load all manifest sources; return usable pages and a log of excluded pages."""
    usable, log = [], []
    for src in manifest['sources']:
        meta = {'law_id': src['law_id'], 'law_year': src['law_year'], 'language': src['language']}
        for p in load_pdf(root / src['local_path'], src['source_id'], src['local_path'], meta):
            issue = p.metadata['quality_issue']
            if issue:
                log.append({'document_id': p.document_id, 'page': p.page, 'chars': len(p.text),
                            'reason': issue, 'sample': p.text[:120]})
            else:
                usable.append(p)
    return usable, log


if __name__ == '__main__':
    # python -m src.ingestion  -> results/ingestion_log.json + results/pages.jsonl (for audit)
    import json
    import sys
    import time
    sys.stdout.reconfigure(encoding='utf-8')
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / 'data' / 'manifest.json').read_text(encoding='utf-8'))
    t0 = time.perf_counter()
    usable, excluded = load_corpus(root, manifest)
    elapsed = time.perf_counter() - t0
    out = root / 'results'
    out.mkdir(exist_ok=True)
    with (out / 'pages.jsonl').open('w', encoding='utf-8') as f:
        for p in usable:
            f.write(json.dumps({'document_id': p.document_id, 'source': p.source, 'page': p.page,
                                'chars': len(p.text), 'metadata': p.metadata, 'text': p.text},
                               ensure_ascii=False) + '\n')
    lens = sorted(len(p.text) for p in usable)
    stats = {'extractor': f'PyMuPDF {pymupdf.VersionBind}', 'usable_pages': len(usable),
             'excluded_pages': excluded, 'total_chars': sum(lens),
             'chars_per_page': {'min': lens[0], 'median': lens[len(lens) // 2], 'max': lens[-1]},
             'footnotes_moved_to_metadata': sum(len(p.metadata['footnotes']) for p in usable),
             'seconds': round(elapsed, 2)}
    (out / 'ingestion_log.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in stats.items() if k != 'excluded_pages'}, ensure_ascii=False))
    for e in excluded:
        print('EXCLUDED', e['document_id'], 'p', e['page'], '-', e['reason'])
