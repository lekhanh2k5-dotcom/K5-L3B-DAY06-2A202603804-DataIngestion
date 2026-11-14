"""Chunking strategies. Chunks never cross a page boundary, so `page` is always exact.

A  fixed_size   : windows of `size` chars with `overlap`, snapped to whitespace (no mid-word cut).
B  by_paragraph : structure-aware. A new chunk starts at every "Chương"/"Điều"; khoản/điểm
                  lines (one per line after normalize_text) are packed until `max_size`;
                  an oversized paragraph is split at "; " / ". " boundaries.
C  = B chunks + metadata filter at query time (no separate chunking).

Both strategies attach the same metadata, including chuong/dieu parsed from headings.
The heading active at the start of a page is carried over from the previous page, so a
chunk that continues an article on the next page still knows its Điều.
Chunk text is NOT enriched with headings (keeps A vs B a chunking-only comparison).
"""
import re
from typing import Any, Iterable

from .models import Chunk, DocumentPage

HEAD_CHUONG = re.compile(r'^Chương\s+([IVXLC]+)\b', re.M)
HEAD_DIEU = re.compile(r'^Điều\s+(\d+[a-z]?)\.\s*(.*)$', re.M)
ALL_CAPS = re.compile(r'^[A-ZĐÀ-Ỹ ,;-]{8,}$')
CARRY_KEY = '_carry'           # heading context at page start, set by chunk_corpus
PAGE_META_KEYS = ('law_id', 'law_year', 'language')


def _headings(text: str) -> list[tuple[int, str, str, str]]:
    """(position, kind, number, title) for every Chương / Điều heading in the page."""
    out = [(m.start(), 'chuong', m.group(1), '') for m in HEAD_CHUONG.finditer(text)]
    out += [(m.start(), 'dieu', m.group(1), m.group(2).strip()) for m in HEAD_DIEU.finditer(text)]
    return sorted(out)


def _context_at(page: DocumentPage, pos: int) -> dict[str, str]:
    ctx = dict(page.metadata.get(CARRY_KEY) or {'chuong': '', 'dieu': '', 'dieu_title': ''})
    for start, kind, num, title in _headings(page.text):
        if start > pos:
            break
        if kind == 'chuong':
            ctx = {'chuong': num, 'dieu': '', 'dieu_title': ''}
        else:
            ctx.update(dieu=num, dieu_title=title)
    return ctx


def _make_chunk(page: DocumentPage, strategy: str, idx: int, start: int, end: int) -> Chunk:
    raw = page.text[start:end]
    lead = len(raw) - len(raw.lstrip())
    text = raw.strip()
    start += lead
    end = start + len(text)
    meta: dict[str, Any] = {k: page.metadata[k] for k in PAGE_META_KEYS if k in page.metadata}
    ctx = _context_at(page, start)
    if not ctx['dieu']:   # chunk starts with a Chương heading: use the first Điều inside it
        inner = [h for h in _headings(page.text) if start <= h[0] < end and h[1] == 'dieu']
        if inner:
            ctx.update(dieu=inner[0][2], dieu_title=inner[0][3])
    meta.update(strategy=strategy, chunk_index=idx, char_start=start, char_end=end, **ctx)
    return Chunk(chunk_id=f'{page.document_id}:p{page.page}:{strategy}:{idx:03d}',
                 document_id=page.document_id, source=page.source, page=page.page,
                 text=text, metadata=meta)


def fixed_size(page: DocumentPage, size: int, overlap: int, strategy: str = 'A') -> list[Chunk]:
    """Overlapping windows of ~`size` chars; cut points snapped back to whitespace."""
    if not 0 <= overlap < size:
        raise ValueError('need 0 <= overlap < size')
    text, n = page.text, len(page.text)
    spans, start = [], 0
    while start < n:
        end = min(start + size, n)
        if end < n:
            cut = max(text.rfind(' ', start + size // 2, end), text.rfind('\n', start + size // 2, end))
            if cut > start:
                end = cut
        spans.append((start, end))
        if end >= n:
            break
        nxt = max(end - overlap, start + 1)
        sp = text.find(' ', nxt, end)            # begin overlap on a word boundary
        start = sp + 1 if sp != -1 else nxt
    return [_make_chunk(page, strategy, i, s, e) for i, (s, e) in enumerate(spans) if text[s:e].strip()]


def _split_long(start: int, end: int, text: str, max_size: int) -> list[tuple[int, int]]:
    """Split one oversized paragraph at '; ' or '. ' (fallback: whitespace)."""
    spans = []
    while end - start > max_size:
        window = text[start:start + max_size]
        cut = max(window.rfind('; '), window.rfind('. '))
        if cut < max_size // 3:
            cut = window.rfind(' ')
        cut = start + (cut + 1 if cut > 0 else max_size)
        spans.append((start, cut))
        start = cut
    spans.append((start, end))
    return spans


def by_paragraph(page: DocumentPage, max_size: int, strategy: str = 'B') -> list[Chunk]:
    """Group paragraphs by Chương/Điều, pack khoản up to max_size, split oversized ones."""
    text = page.text
    paras, pos = [], 0                            # (start, end, is_heading_only, starts_group)
    for line in text.split('\n'):
        s, e = pos, pos + len(line)
        pos = e + 1
        if not line.strip():
            continue
        is_chuong = bool(HEAD_CHUONG.match(line))
        is_dieu = bool(HEAD_DIEU.match(line))
        paras.append((s, e, is_chuong or bool(ALL_CAPS.match(line)), is_chuong or is_dieu))

    groups: list[list[tuple[int, int, bool]]] = []
    heading_only = False
    for s, e, is_heading, starts_group in paras:
        # "Chương II" + title + "Điều 10. ..." stay together: a Điều directly after a
        # heading-only group does not open a new group.
        if not groups or (starts_group and not heading_only):
            groups.append([])
            heading_only = True
        groups[-1].append((s, e, is_heading))
        heading_only = heading_only and is_heading

    spans = []
    for group in groups:
        cur_s = cur_e = None
        cur_heading_only = False
        for s, e, is_heading in group:
            for ps, pe in _split_long(s, e, text, max_size):
                # never flush a chunk that holds only headings: a heading stays with the
                # paragraph that follows it (chunk may exceed max_size by the heading length)
                if cur_s is not None and pe - cur_s > max_size and not cur_heading_only:
                    spans.append((cur_s, cur_e))
                    cur_s = None
                if cur_s is None:
                    cur_s = ps
                    cur_heading_only = True
                cur_e = pe
                cur_heading_only = cur_heading_only and is_heading
        if cur_s is not None:
            spans.append((cur_s, cur_e))
    return [_make_chunk(page, strategy, i, s, e) for i, (s, e) in enumerate(spans)]


def chunk_corpus(pages: Iterable[DocumentPage], strategy: str, **params: int) -> list[Chunk]:
    """Chunk pages in reading order, carrying the active Chương/Điều across pages."""
    chunks: list[Chunk] = []
    carry: dict[str, dict] = {}
    for page in sorted(pages, key=lambda p: (p.document_id, p.page)):
        page.metadata[CARRY_KEY] = carry.get(page.document_id)
        if strategy == 'A':
            chunks += fixed_size(page, params['size'], params['overlap'], strategy)
        elif strategy == 'B':
            chunks += by_paragraph(page, params['max_size'], strategy)
        else:
            raise ValueError(f'unknown chunking strategy {strategy!r}')
        carry[page.document_id] = _context_at(page, len(page.text))
        page.metadata.pop(CARRY_KEY)
    return chunks


if __name__ == '__main__':
    # python -m src.chunking -> results/chunks_{A,B}.jsonl + results/chunk_stats.json
    import json
    import sys
    from pathlib import Path

    from .ingestion import load_corpus

    sys.stdout.reconfigure(encoding='utf-8')
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / 'configs' / 'strategies.json').read_text(encoding='utf-8'))
    manifest = json.loads((root / 'data' / 'manifest.json').read_text(encoding='utf-8'))
    pages, _ = load_corpus(root, manifest)
    questions = json.loads((root.parent / 'benchmark' / 'questions.json').read_text(encoding='utf-8'))['questions']
    dev = [q for q in questions if q['split'] == 'dev']   # never inspect test before the final run
    squash = lambda t: re.sub(r'\s+', '', t)  # noqa: E731

    stats = {}
    for name in ('A', 'B'):
        cfg = config['chunking'][name]
        chunks = chunk_corpus(pages, name, **cfg['params'])
        with (root / 'results' / f'chunks_{name}.jsonl').open('w', encoding='utf-8') as f:
            for c in chunks:
                f.write(json.dumps(c.__dict__, ensure_ascii=False) + '\n')
        lens = sorted(len(c.text) for c in chunks)
        q = lambda p: lens[min(len(lens) - 1, int(p * len(lens)))]  # noqa: E731
        split_dev = []
        for qq in dev:
            golds = {(qq['gold_source_id'], qq['gold_page'])} | {(a['source_id'], a['page']) for a in qq.get('alternative_gold', [])}
            ev = squash(qq['evidence_quote'])
            if not any((c.document_id, c.page) in golds and ev in squash(c.text) for c in chunks):
                split_dev.append(qq['id'])
        stats[name] = {'params': cfg['params'], 'chunks': len(chunks), 'total_chars': sum(lens),
                       'len_min': lens[0], 'len_median': q(0.5), 'len_p90': q(0.9), 'len_max': lens[-1],
                       'missing_dieu_metadata': sum(1 for c in chunks if not c.metadata['dieu']),
                       'dev_evidence_split_across_chunks': split_dev}
        print(name, json.dumps(stats[name], ensure_ascii=False))
    (root / 'results' / 'chunk_stats.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
