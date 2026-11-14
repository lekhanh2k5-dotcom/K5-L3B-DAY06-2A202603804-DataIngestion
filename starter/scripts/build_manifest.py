"""Build data/manifest.json: source, license, sha256 and per-page counting decisions.

Counting rule (documented in the manifest):
  - a physical PDF page counts as a content page if, after extraction, it has
    >= MIN_CHARS characters and is not listed in EXCLUDE (signature / garbled pages);
  - excluded pages are kept in the manifest with a reason, never silently dropped.
Run from starter/:  .venv/Scripts/python.exe scripts/build_manifest.py
"""
import hashlib
import json
import sys
import unicodedata
from pathlib import Path


sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.ingestion import MIN_CHARS as _MIN, load_pdf  # noqa: E402
MIN_CHARS = _MIN
ACCESSED_AT = '2026-11-14'

SOURCES = [
    {
        'source_id': 'luat-gtdb-2008',
        'file': 'data/raw/luat23_2008_vbhn2019_sgu.pdf',
        'title': 'Luật Giao thông đường bộ số 23/2008/QH12 — Văn bản hợp nhất 15/VBHN-VPQH ngày 05/7/2019',
        'source_url': 'https://sgu.edu.vn/wp-content/uploads/2024/05/Luat-Giao-thong-duong-bo-nam-2019.pdf',
        'snapshot': 'Bản in Công báo số 729+730 ngày 05/9/2019 (hợp nhất sửa đổi bởi Luật 35/2018/QH14 và Luật 44/2019/QH14)',
        'law_id': '23/2008/QH12',
        'law_year': 2008,
        # Hiệu lực ghi theo văn bản: có hiệu lực 01/7/2009 (Điều 88). Việc hết hiệu lực
        # từ 01/01/2025 là thông tin ngoài văn bản này -> không dùng làm metadata lọc.
        'effective_from': '2009-07-01',
        'exclude': {61: 'Trang trống (không có text)'},
    },
    {
        'source_id': 'luat-ttatgtdb-2024',
        'file': 'data/raw/vbhn55_2026_chinhphu.pdf',
        'title': 'Luật Trật tự, an toàn giao thông đường bộ số 36/2024/QH15 — Văn bản hợp nhất 55/VBHN-VPQH (2026)',
        'source_url': 'https://datafiles.chinhphu.vn/cpp/files/vbpq/2026/3/55-vbhn-vpqh.pdf',
        'snapshot': 'Hợp nhất sửa đổi bởi Luật 118/2025/QH15 (hiệu lực 01/7/2026)',
        'law_id': '36/2024/QH15',
        'law_year': 2024,
        'effective_from': '2025-01-01',
        'exclude': {74: 'Phần cuối Điều 89 (khoản 4 trở đi) + trang xác thực: lớp text sai, mất dấu tiếng Việt (vd. "Lu~t", "Qu6c h()i") -> nội dung bị mất, không OCR'},
    },
]
LICENSE = ('Văn bản quy phạm pháp luật và văn bản hợp nhất của cơ quan nhà nước: '
           'không thuộc đối tượng bảo hộ quyền tác giả theo Điều 15 Luật Sở hữu trí tuệ. '
           'Tài liệu công khai, không chứa dữ liệu cá nhân.')


def main() -> None:
    manifest = {'accessed_at': ACCESSED_AT, 'counting_rule': (
        f'Trang vật lý được tính là trang nội dung nếu text sau trích xuất PyMuPDF + chuẩn hóa (src/ingestion.py) >= {MIN_CHARS} ký tự '
        'và không bị đánh dấu lỗi (trang trống; trích xuất sai dấu tiếng Việt).'),
        'sources': []}
    total = 0
    for s in SOURCES:
        path = ROOT / s['file']
        pages = []
        for pg in load_pdf(path, s['source_id'], s['file']):
            auto = pg.metadata['quality_issue']
            reason = s['exclude'].get(pg.page) or auto
            if reason and auto and reason != auto:
                reason = f'{reason}; auto-check: {auto}'
            pages.append({'page_id': f"{s['source_id']}:p{pg.page}", 'page': pg.page, 'chars': len(pg.text),
                          'counted': reason is None, **({'excluded_reason': reason} if reason else {})})
        counted = [p for p in pages if p['counted']]
        total += len(counted)
        manifest['sources'].append({
            'source_id': s['source_id'], 'title': s['title'], 'source_path_or_url': s['source_url'],
            'local_path': s['file'], 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'snapshot_or_version': s['snapshot'], 'license_or_permission': LICENSE,
            'accessed_at': ACCESSED_AT, 'language': 'vi',
            'law_id': s['law_id'], 'law_year': s['law_year'], 'effective_from': s['effective_from'],
            'physical_pages': len(pages), 'content_pages': len(counted),
            'content_chars': sum(p['chars'] for p in counted), 'pages': pages,
        })
        print(f"{s['source_id']}: {len(pages)} physical, {len(counted)} counted, "
              f"excluded={[ (p['page'], p['excluded_reason']) for p in pages if not p['counted']]}")
    manifest['total_content_pages'] = total
    out = ROOT / 'data' / 'manifest.json'
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Total content pages: {total} -> {out}')


if __name__ == '__main__':
    main()
