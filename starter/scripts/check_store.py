"""Store checks (not benchmark): changed-document handling + filtered search smoke test.

1. Change test on a throwaway collection: sync 2 pages of B chunks, then sync again with one
   chunk text edited and one chunk removed -> expect embedded=1, deleted_obsolete=1.
2. Smoke query NOT in the benchmark, with and without law_year filter.
Run from starter/: .venv/Scripts/python.exe scripts/check_store.py
"""
import copy
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.chunking import chunk_corpus  # noqa: E402
from src.index import build  # noqa: E402
from src.ingestion import load_corpus  # noqa: E402

config = json.loads((ROOT / 'configs' / 'strategies.json').read_text(encoding='utf-8'))
manifest = json.loads((ROOT / 'data' / 'manifest.json').read_text(encoding='utf-8'))
embedder, store = build(config)
pages, _ = load_corpus(ROOT, manifest)
sample = [p for p in pages if p.document_id == 'luat-gtdb-2008' and p.page in (30, 31)]
chunks = chunk_corpus(sample, 'B', max_size=1000)

name = 'changetest'
try:
    print('v1      :', store.sync(name, chunks, embedder.embed_documents))
    v2 = copy.deepcopy(chunks)
    v2[0].text += ' (sửa đổi giả lập)'
    v2.pop()                                      # simulate a removed paragraph
    print('v2 change:', store.sync(name, v2, embedder.embed_documents))
finally:
    store.client.delete_collection(f'day6-{name}')

q = 'Người ngồi sau xe máy có phải đội mũ bảo hiểm không?'
vec = embedder.embed_query(q)
for flt in (None, {'law_year': 2008}, {'law_year': 2024}):
    hits = store.search('B', vec, 3, flt)
    print(f'\nfilter={flt}')
    for h in hits:
        m = h['metadata']
        print(f"  #{h['rank']} {h['score']:.3f} {m['law_year']} p{m['page']} Điều {m['dieu']} | {h['text'][:90]!r}")
print('\nusage', embedder.usage)
