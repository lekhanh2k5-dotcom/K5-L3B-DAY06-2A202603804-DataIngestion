"""Vector store: Chroma PersistentClient (on-disk), cosine distance, metadata filtering.

Replaces the starter's PgVectorStore because Docker/pgvector is unavailable on this machine.
Chroma uses an HNSW index (approximate nearest neighbour); `where` filters are applied by
Chroma together with the vector search, so a filtered query only returns matching chunks.

One collection per chunk set ("A", "B"); strategy C queries collection "B" with a filter.
Re-ingestion: IDs are stable, unchanged chunks (same text hash) are not re-embedded,
changed chunks are re-embedded and upserted, obsolete chunks of the re-ingested documents
are deleted.
"""
import hashlib
from typing import Any, Callable

import chromadb

from .models import Chunk

SCALAR = (str, int, float, bool)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


class ChromaStore:
    def __init__(self, path: str, dimensions: int, model_name: str) -> None:
        if dimensions <= 0:
            raise ValueError('dimensions must be positive')
        self.client = chromadb.PersistentClient(path=path)
        self.dimensions = dimensions
        self.model_name = model_name

    def collection(self, chunk_set: str):
        return self.client.get_or_create_collection(
            f'day6-{chunk_set}', metadata={'hnsw:space': 'cosine', 'embedding_model': self.model_name,
                                           'dimensions': self.dimensions})

    def _check_collection(self, col) -> None:
        meta = col.metadata or {}
        if meta.get('embedding_model') not in (None, self.model_name) or \
                meta.get('dimensions') not in (None, self.dimensions):
            raise RuntimeError(f'collection {col.name} was built with {meta}; refusing to mix models')

    def sync(self, chunk_set: str, chunks: list[Chunk],
             embed: Callable[[list[str]], list[list[float]]]) -> dict[str, int]:
        """Upsert chunks for the documents they belong to; embed only new/changed text."""
        col = self.collection(chunk_set)
        self._check_collection(col)
        ids = [c.chunk_id for c in chunks]
        if len(set(ids)) != len(ids):
            raise ValueError('duplicate chunk_id in input')
        docs = sorted({c.document_id for c in chunks})
        existing = col.get(where={'document_id': {'$in': docs}}, include=['metadatas'])
        old_hash = {i: m.get('text_hash') for i, m in zip(existing['ids'], existing['metadatas'])}

        todo = [c for c in chunks if old_hash.get(c.chunk_id) != text_hash(c.text)]
        if todo:
            vectors = embed([c.text for c in todo])
            self.upsert(col, todo, vectors)
        obsolete = sorted(set(old_hash) - set(ids))
        if obsolete:
            col.delete(ids=obsolete)
        return {'input_chunks': len(chunks), 'embedded': len(todo),
                'unchanged': len(chunks) - len(todo), 'deleted_obsolete': len(obsolete),
                'collection_count': col.count()}

    def upsert(self, col, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError(f'{len(chunks)} chunks but {len(vectors)} vectors')
        bad = [c.chunk_id for c, v in zip(chunks, vectors) if len(v) != self.dimensions]
        if bad:
            raise ValueError(f'wrong vector dimensions for {bad[:3]}')
        metas = []
        for c in chunks:
            m = {k: v for k, v in c.metadata.items() if isinstance(v, SCALAR)}
            m.update(document_id=c.document_id, source=c.source, page=c.page, text_hash=text_hash(c.text))
            metas.append(m)
        for i in range(0, len(chunks), 1000):
            col.upsert(ids=[c.chunk_id for c in chunks[i:i + 1000]], embeddings=vectors[i:i + 1000],
                       documents=[c.text for c in chunks[i:i + 1000]], metadatas=metas[i:i + 1000])

    def search(self, chunk_set: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Top-k by cosine distance; optional equality filter on scalar metadata fields."""
        if len(query_vector) != self.dimensions:
            raise ValueError('query vector has wrong dimensions')
        col = self.collection(chunk_set)
        where = None
        if filters:
            clauses = [{k: {'$eq': v}} for k, v in filters.items()]
            where = clauses[0] if len(clauses) == 1 else {'$and': clauses}
        res = col.query(query_embeddings=[query_vector], n_results=top_k, where=where,
                        include=['documents', 'metadatas', 'distances'])
        return [{'rank': r + 1, 'chunk_id': i, 'text': d, 'distance': dist, 'score': 1 - dist, 'metadata': m}
                for r, (i, d, m, dist) in enumerate(zip(res['ids'][0], res['documents'][0],
                                                        res['metadatas'][0], res['distances'][0]))]
