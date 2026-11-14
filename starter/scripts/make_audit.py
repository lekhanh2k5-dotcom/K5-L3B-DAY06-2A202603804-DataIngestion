"""Create manual-audit sheets (CSV, UTF-8 BOM for Excel) in results/audit/.

1. coherence.csv  — 10 source positions x strategies A/B/C (C uses the same chunks as B).
   Position rule (fixed before any coherence label is seen, independent of scores):
   sort usable pages by (document_id, page); take every 13th page starting at index 6
   (6, 19, 32, ... -> 10 pages spread over both laws); position = the paragraph that
   contains the midpoint character of that page. For each strategy, the chunk covering
   the position (if several overlap, the one where it is most central) is shown.
2. metadata.csv   — 5 test questions x top-3 x A/B/C with automatic checks pre-filled.
3. grounding.csv  — 5 test questions x A/B/C with the top-3 texts.
Label columns are left EMPTY for the human rater (the author). Do not edit other columns.
"""
import csv
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / 'results'
OUT = RES / 'audit'
OUT.mkdir(exist_ok=True)


def jl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]


def write(name: str, rows: list[dict]) -> None:
    with (OUT / name).open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f'{name}: {len(rows)} rows')


pages = sorted(jl(RES / 'pages.jsonl'), key=lambda p: (p['document_id'], p['page']))
page_by = {(p['document_id'], p['page']): p for p in pages}
chunks = {s: jl(RES / f'chunks_{s}.jsonl') for s in 'AB'}
manifest = json.loads((ROOT / 'data' / 'manifest.json').read_text(encoding='utf-8'))
law_year = {s['source_id']: s['law_year'] for s in manifest['sources']}

# ---------- 1. coherence
rows = []
picked = pages[6::13][:10]
for i, p in enumerate(picked, 1):
    mid = len(p['text']) // 2
    para_start = p['text'].rfind('\n', 0, mid) + 1
    para_end = p['text'].find('\n', mid)
    para_end = len(p['text']) if para_end == -1 else para_end
    pos_id = f'pos{i:02d}'
    for s in 'ABC':
        pool = chunks['A' if s == 'A' else 'B']
        cover = [c for c in pool if c['document_id'] == p['document_id'] and c['page'] == p['page']
                 and c['metadata']['char_start'] <= mid < c['metadata']['char_end']]
        best = min(cover, key=lambda c: abs((c['metadata']['char_start'] + c['metadata']['char_end']) / 2 - mid))
        rows.append({'position_id': pos_id, 'page_id': f"{p['document_id']}:p{p['page']}",
                     'position_paragraph': p['text'][para_start:para_end][:400],
                     'strategy': s, 'chunk_id': best['chunk_id'],
                     'note': 'C dùng cùng chunk với B → nhãn phải giống B' if s == 'C' else '',
                     'chunk_len': len(best['text']), 'chunk_text': best['text'],
                     'label_0_1_2': '', 'reason': ''})
write('coherence.csv', rows)

# ---------- 2. metadata (test only)
traces = jl(RES / 'traces_test.jsonl')
squash = lambda t: re.sub(r'\s+', '', t)  # noqa: E731
rows = []
for t in traces:
    for h in t['hits']:
        m = h['metadata']
        pg = page_by.get((m['document_id'], m['page']))
        in_page = bool(pg) and squash(h['text']) in squash(pg['text'])
        year_ok = law_year.get(m['document_id']) == m.get('law_year')
        # dieu check: heading "Điều N." on this page before the chunk, or carried from earlier pages
        dieu_ok = ''
        if m.get('dieu'):
            heads = []
            for (d, pno), pp in page_by.items():
                if d == m['document_id'] and pno <= m['page']:
                    limit = m['char_end'] if pno == m['page'] else len(pp['text'])
                    heads += [(pno, x.start(), x.group(1)) for x in re.finditer(r'^Điều\s+(\d+[a-z]?)\.', pp['text'][:limit], re.M)]
            dieu_ok = str(m['dieu'] in [h_[2] for h_ in sorted(heads)[-3:]])
        rows.append({'strategy': t['strategy'], 'question_id': t['id'], 'question_filter': json.dumps(t['question_filter'], ensure_ascii=False) if t['question_filter'] else '',
                     'rank': h['rank'], 'chunk_id': h['chunk_id'], 'source': m['source'], 'page': m['page'],
                     'document_id': m['document_id'], 'law_year': m.get('law_year'), 'dieu': m.get('dieu'),
                     'auto_text_found_on_page': in_page, 'auto_law_year_matches_manifest': year_ok,
                     'auto_dieu_plausible': dieu_ok,
                     'auto_respects_filter': ('' if not t['question_filter'] else
                                              all(m.get(k) == v for k, v in t['question_filter'].items())),
                     'chunk_text_start': h['text'][:200],
                     'human_metadata_complete_and_correct_Y_N': '', 'error_note': ''})
write('metadata.csv', rows)

# ---------- 3. grounding (test only)
rows = []
for t in traces:
    r = {'strategy': t['strategy'], 'question_id': t['id'], 'question': t['question'],
         'question_filter': json.dumps(t['question_filter'], ensure_ascii=False) if t['question_filter'] else '',
         'filter_applied': json.dumps(t['filter_applied'], ensure_ascii=False) if t['filter_applied'] else '',
         'expected_answer': t['expected_answer'], 'gold': ' | '.join(t['gold']),
         'evidence_quote': t['evidence_quote'], 'auto_evidence_hit@3_proxy': t['hit@3']}
    for h in t['hits']:
        m = h['metadata']
        r[f"top{h['rank']}"] = f"[{h['chunk_id']} | {m['law_year']} | Điều {m.get('dieu')} | score {h['score']:.3f}]\n{h['text']}"
    r.update({'label_0_1_2': '', 'reason': ''})
    rows.append(r)
write('grounding.csv', rows)
