"""Build / refresh the Chroma collections for chunk sets A and B.

python -m src.index            # build (embeds only new/changed chunks)
Writes results/index_log.json with timings, tokens, cost and a re-ingestion check
(second sync of the same data must embed 0 chunks and leave counts unchanged).
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import chromadb
from dotenv import load_dotenv

from .chunking import chunk_corpus
from .embeddings import OpenRouterEmbedder
from .ingestion import load_corpus
from .store import ChromaStore

ROOT = Path(__file__).resolve().parents[1]


def build(config: dict) -> tuple[OpenRouterEmbedder, ChromaStore]:
    load_dotenv(ROOT / '.env')
    emb_cfg = config['embedding']
    if os.getenv('EMBEDDING_MODEL') and os.getenv('EMBEDDING_MODEL') != emb_cfg['model']:
        raise RuntimeError('EMBEDDING_MODEL in .env differs from configs/strategies.json')
    embedder = OpenRouterEmbedder(emb_cfg['model'], emb_cfg['dimensions'])
    store = ChromaStore(str(ROOT / os.getenv('CHROMA_PATH', 'chroma_db')), embedder.dimensions, embedder.model_name)
    return embedder, store


def main() -> None:
    sys.stdout.reconfigure(encoding='utf-8')
    config = json.loads((ROOT / 'configs' / 'strategies.json').read_text(encoding='utf-8'))
    manifest = json.loads((ROOT / 'data' / 'manifest.json').read_text(encoding='utf-8'))
    embedder, store = build(config)
    pages, _ = load_corpus(ROOT, manifest)
    log = {'run_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
           'embedding_model': embedder.model_name, 'dimensions': embedder.dimensions,
           'chromadb_version': chromadb.__version__, 'chunk_sets': {}}
    for name, cfg in config['chunking'].items():
        chunks = chunk_corpus(pages, name, **cfg['params'])
        before = dict(embedder.usage)
        t0 = time.perf_counter()
        first = store.sync(name, chunks, embedder.embed_documents)
        t1 = time.perf_counter()
        second = store.sync(name, chunks, embedder.embed_documents)      # re-ingestion check
        t2 = time.perf_counter()
        used = {k: embedder.usage[k] - before[k] for k in before}
        log['chunk_sets'][name] = {'params': cfg['params'], 'first_sync': first, 'first_sync_seconds': round(t1 - t0, 2),
                                   'resync_same_data': second, 'resync_seconds': round(t2 - t1, 2),
                                   'embedding_usage': used,
                                   'no_duplicates': second['embedded'] == 0 and
                                                    second['collection_count'] == first['collection_count'] == len(chunks)}
        print(name, json.dumps(log['chunk_sets'][name], ensure_ascii=False))
    log['total_usage_incl_probe'] = embedder.usage
    (ROOT / 'results' / 'index_log.json').write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding='utf-8')
    print('total', embedder.usage)


if __name__ == '__main__':
    main()
