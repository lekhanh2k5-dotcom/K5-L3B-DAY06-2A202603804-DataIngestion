"""Setup check for Chroma (persistent) + OpenRouter embeddings. Not part of the pipeline."""
import os
import sys
from pathlib import Path

import chromadb
from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')

# 1. Chroma: persistent client, cosine collection, write + read + metadata filter.
chroma_path = ROOT / os.getenv('CHROMA_PATH', 'chroma_db')
client = chromadb.PersistentClient(path=str(chroma_path))
col = client.get_or_create_collection('setup-check', metadata={'hnsw:space': 'cosine'})
col.upsert(ids=['a', 'b'], embeddings=[[1.0, 0.0], [0.0, 1.0]],
           metadatas=[{'year': 2024}, {'year': 2025}], documents=['x', 'y'])
res = col.query(query_embeddings=[[1.0, 0.1]], n_results=1, where={'year': 2025})
assert res['ids'][0] == ['b'], f'metadata filter failed: {res["ids"]}'
client.delete_collection('setup-check')
print(f'Chroma {chromadb.__version__} OK | path: {chroma_path} | cosine + filter OK')

# 2. OpenRouter embeddings: one real call, report dimensions.
key = os.getenv('OPENROUTER_API_KEY')
model = os.getenv('EMBEDDING_MODEL')
if not key or not model:
    sys.exit('OPENROUTER_API_KEY or EMBEDDING_MODEL missing in starter/.env')
api = OpenAI(api_key=key, base_url=os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1'))
try:
    resp = api.embeddings.create(model=model, input=['Kiểm tra embedding tiếng Việt.'])
except Exception as exc:  # report the real provider error; never fall back to mock vectors
    sys.exit(f'OpenRouter embedding call failed: {type(exc).__name__}: {exc}')
vec = resp.data[0].embedding
usage = getattr(resp, 'usage', None)
print(f'OpenRouter OK | model: {model} | dimensions: {len(vec)} | usage: {usage}')
print('Setup OK. Pipeline functions still need to be implemented.')
