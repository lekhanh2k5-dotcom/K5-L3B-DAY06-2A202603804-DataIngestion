"""Aggregate automatic metrics + manual audit labels -> results/summary.json (+ printed tables).

Run from starter/: .venv/Scripts/python.exe scripts/summarize_results.py
"""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / 'results'


def rd(name: str) -> list[dict]:
    with (RES / 'audit' / name).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


coh, meta, grd = rd('coherence.csv'), rd('metadata.csv'), rd('grounding.csv')
metrics = {s: json.loads((RES / f'metrics_{s}.json').read_text(encoding='utf-8')) for s in ('dev', 'test')}
index_log = json.loads((RES / 'index_log.json').read_text(encoding='utf-8'))
chunk_stats = json.loads((RES / 'chunk_stats.json').read_text(encoding='utf-8'))
config = json.loads((ROOT / 'configs' / 'strategies.json').read_text(encoding='utf-8'))

out = {'retrieval': {}, 'manual': {}, 'resources': {}}
for s in ('A', 'B', 'C'):
    out['retrieval'][s] = {sp: {k: metrics[sp]['metrics'][s][sp][k] for k in
                                ('hit@1', 'evidence_hit@3', 'page_hit@3', 'filter_compliance', 'misses@3', 'mean_search_ms')}
                           for sp in ('dev', 'test')}
    c = [int(r['label_0_1_2']) for r in coh if r['strategy'] == s]
    g = [int(r['label_0_1_2']) for r in grd if r['strategy'] == s]
    m = [r for r in meta if r['strategy'] == s]
    out['manual'][s] = {
        'coherence_mean': round(sum(c) / len(c), 2), 'coherence_n': len(c), 'coherence_dist': dict(sorted(Counter(c).items())),
        'metadata_correct': f"{sum(r['human_metadata_complete_and_correct_Y_N'] == 'Y' for r in m)}/{len(m)}",
        'grounding_dist': {k: Counter(g).get(k, 0) for k in (0, 1, 2)}, 'grounding_mean': round(sum(g) / len(g), 2),
        'grounding_by_question': {r['question_id']: int(r['label_0_1_2']) for r in grd if r['strategy'] == s},
    }
    cs = config['strategies'][s]['chunks']
    log = index_log['chunk_sets'][cs]
    out['resources'][s] = {'chunk_set': cs, 'chunks': chunk_stats[cs]['chunks'], 'total_chars': chunk_stats[cs]['total_chars'],
                           'len_median': chunk_stats[cs]['len_median'], 'len_max': chunk_stats[cs]['len_max'],
                           'embed_tokens': log['embedding_usage']['prompt_tokens'], 'embed_cost_usd': log['embedding_usage']['cost_usd'],
                           'index_seconds': log['first_sync_seconds'], 'shared_with_B': s == 'C'}
out['totals'] = {'embedding_usage_index_incl_probe': index_log['total_usage_incl_probe'],
                 'query_usage_dev': metrics['dev']['query_embedding_usage'], 'query_usage_test': metrics['test']['query_embedding_usage']}
(RES / 'summary.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')

print('| Strategy | Split | Hit@1 | Evidence Hit@3 | Page Hit@3 | Filter | Chunks | Index time | Cost |')
for s in 'ABC':
    r = out['resources'][s]
    for sp in ('dev', 'test'):
        x = out['retrieval'][s][sp]
        print(f"| {s} | {sp} | {x['hit@1']} | {x['evidence_hit@3']} | {x['page_hit@3']} | {x['filter_compliance']} | {r['chunks']} | {r['index_seconds']}s | ${r['embed_cost_usd']:.4f} |")
print('\n| Strategy | Coherence /2 (n) | Metadata | Grounding 0/1/2 | Grounding /2 |')
for s in 'ABC':
    m = out['manual'][s]
    print(f"| {s} | {m['coherence_mean']} ({m['coherence_n']}) {m['coherence_dist']} | {m['metadata_correct']} | {m['grounding_dist']} | {m['grounding_mean']} {m['grounding_by_question']} |")
print('\ntotals', json.dumps(out['totals']))
