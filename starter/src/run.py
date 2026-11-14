"""Day 06 pipeline entry point.

  python -m src.run --split dev     # 1) run A/B/C on dev, write traces + metrics, select strategy
  python -m src.run --split test    # 2) only after results/selection.json exists: run test once

Indexing (ingest -> chunk -> embed -> store) is `python -m src.index`; this script checks
the collections exist and match the current chunking before querying.
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .chunking import chunk_corpus
from .evaluation import evaluate_query, summarize
from .index import build
from .ingestion import load_corpus

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'results'


def select_strategy(summary: dict, chunk_counts: dict, config: dict) -> dict:
    """Apply the pre-registered rule on dev metrics (grounding is manual -> noted, not used here)."""
    def compliance(s: str) -> float:
        n, N = summary[s]['dev']['filter_compliance'].split('/')
        return int(n) / int(N)

    rule = config['selection_rule']
    amended = 'amendment' in rule
    rows = []
    for s, scfg in config['strategies'].items():
        d = summary[s]['dev']
        key = (d['hit@3_rate'], d['hit@1_rate'])
        key += (compliance(s),) if amended else ()
        key += (-chunk_counts[scfg['chunks']],)
        rows.append((key, s))
    rows.sort(key=lambda r: r[0], reverse=True)
    best_key = rows[0][0]
    tied = [s for k, s in rows if k == best_key]      # still tied after every automatic step
    return {'selected': rows[0][1] if len(tied) == 1 else None,
            'ranking': [s for _, s in rows], 'still_tied': tied if len(tied) > 1 else [],
            'keys': {s: k for k, s in rows},
            'rule': rule['order'], 'amendment': rule.get('amendment'),
            'note': 'unresolved tie: needs manual step (grounding) or report as tie' if len(tied) > 1 else ''}


def main() -> None:
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('--split', choices=['dev', 'test'], required=True)
    args = ap.parse_args()

    config = json.loads((ROOT / 'configs' / 'strategies.json').read_text(encoding='utf-8'))
    manifest = json.loads((ROOT / 'data' / 'manifest.json').read_text(encoding='utf-8'))
    bench = json.loads((ROOT.parent / 'benchmark' / 'questions.json').read_text(encoding='utf-8'))
    if bench.get('version') != 'v1-final':
        raise SystemExit('benchmark is not frozen (version != v1-final)')
    if args.split == 'test' and not (RESULTS / 'selection.json').exists():
        raise SystemExit('Run --split dev and write results/selection.json before touching test.')
    questions = [q for q in bench['questions'] if q['split'] == args.split]
    pages, _ = load_corpus(ROOT, manifest)
    if len(pages) < 30:
        raise SystemExit(f'only {len(pages)} usable pages (<30)')

    embedder, store = build(config)
    chunk_counts = {}
    for name, cfg in config['chunking'].items():       # index must match current chunking
        expected = len(chunk_corpus(pages, name, **cfg['params']))
        have = store.collection(name).count()
        if have != expected:
            raise SystemExit(f'collection {name} has {have} chunks, chunking gives {expected}: run python -m src.index')
        chunk_counts[name] = have

    qvec = {q['id']: embedder.embed_query(q['question']) for q in questions}   # same vector for A/B/C
    traces = []
    for s, scfg in config['strategies'].items():
        for q in questions:
            flt = q['filter'] if (scfg['use_filter'] and q.get('filter')) else None
            t0 = time.perf_counter()
            hits = store.search(scfg['chunks'], qvec[q['id']], config['top_k'], flt)
            ms = (time.perf_counter() - t0) * 1000
            tr = evaluate_query(q, hits, flt)
            tr.update(strategy=s, chunk_set=scfg['chunks'], search_ms=round(ms, 1))
            traces.append(tr)

    run_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with (RESULTS / f'traces_{args.split}.jsonl').open('w', encoding='utf-8') as f:
        for t in traces:
            f.write(json.dumps(t, ensure_ascii=False) + '\n')
    summary = summarize(traces)
    out = {'run_at': run_at, 'split': args.split, 'embedding_model': embedder.model_name,
           'query_embedding_usage': embedder.usage, 'chunk_counts': chunk_counts, 'metrics': summary}
    (RESULTS / f'metrics_{args.split}.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f'== {args.split} ({len(questions)} questions) | run_at {run_at}')
    print(f"{'strategy':8} {'Hit@1':>7} {'EvHit@3':>8} {'PageHit@3':>10} {'filter':>7}  misses@3")
    for s, rows in summary.items():
        r = rows[args.split]
        print(f"{s:8} {r['hit@1']:>7} {r['evidence_hit@3']:>8} {r['page_hit@3']:>10} {r['filter_compliance']:>7}  {r['misses@3']}")
    print('query embedding usage:', embedder.usage)

    if args.split == 'dev':
        sel = select_strategy(summary, chunk_counts, config)
        sel['decided_at'] = run_at
        (RESULTS / 'selection.json').write_text(json.dumps(sel, ensure_ascii=False, indent=2), encoding='utf-8')
        print('selection:', json.dumps(sel, ensure_ascii=False))


if __name__ == '__main__':
    main()
