"""Automatic retrieval scoring + per-query traces.

Definition (GUIDE §4.1): a retrieved chunk is an *evidence hit* when it belongs to a gold
(source, page) — primary or alternative — AND contains the full evidence_quote.
Matching: NFC + whitespace removed (same as scripts/verify_benchmark.py).
Hit@1 = top-1 is an evidence hit; Evidence Hit@3 = at least one evidence hit in top-3.
We also record page_hit (gold page retrieved but evidence incomplete) to diagnose
evidence split across chunks. Human labels (coherence, grounding) are NOT inferred here.
"""
import re
import unicodedata
from collections import defaultdict
from typing import Any


def _squash(text: str) -> str:
    return re.sub(r'\s+', '', unicodedata.normalize('NFC', text))


def gold_pages(question: dict[str, Any]) -> set[tuple[str, int]]:
    golds = {(question['gold_source_id'], int(question['gold_page']))}
    golds |= {(a['source_id'], int(a['page'])) for a in question.get('alternative_gold', [])}
    return golds


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]],
                   filter_applied: dict[str, Any] | None = None) -> dict[str, Any]:
    golds = gold_pages(question)
    evidence = _squash(question['evidence_quote'])
    scored = []
    for h in hits:
        m = h['metadata']
        on_gold_page = (m['document_id'], int(m['page'])) in golds
        scored.append({**h, 'on_gold_page': on_gold_page,
                       'evidence_hit': on_gold_page and evidence in _squash(h['text'])})
    flt = question.get('filter')
    compliance = None
    if flt:   # does top-3 respect the filter the user asked for (whether or not it was applied)?
        compliance = all(all(h['metadata'].get(k) == v for k, v in flt.items()) for h in hits)
    return {
        'id': question['id'], 'split': question['split'], 'type': question.get('type'),
        'question': question['question'], 'question_filter': flt, 'filter_applied': filter_applied,
        'gold': sorted(f'{s}:p{p}' for s, p in golds), 'evidence_quote': question['evidence_quote'],
        'expected_answer': question['expected_answer'],
        'hit@1': bool(scored and scored[0]['evidence_hit']),
        'hit@3': any(h['evidence_hit'] for h in scored),
        'page_hit@3': any(h['on_gold_page'] for h in scored),
        'filter_compliant_top3': compliance,
        'hits': scored,
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per strategy and split as n/N (not only %)."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for t in traces:
        groups[(t['strategy'], t['split'])].append(t)
    out: dict[str, Any] = {}
    for (strategy, split), ts in sorted(groups.items()):
        n = len(ts)
        flt = [t for t in ts if t['question_filter']]
        row = {
            'N': n,
            'hit@1': f"{sum(t['hit@1'] for t in ts)}/{n}",
            'evidence_hit@3': f"{sum(t['hit@3'] for t in ts)}/{n}",
            'page_hit@3': f"{sum(t['page_hit@3'] for t in ts)}/{n}",
            'filter_compliance': f"{sum(bool(t['filter_compliant_top3']) for t in flt)}/{len(flt)}" if flt else 'N/A',
            'hit@1_rate': round(sum(t['hit@1'] for t in ts) / n, 3),
            'hit@3_rate': round(sum(t['hit@3'] for t in ts) / n, 3),
            'misses@3': [t['id'] for t in ts if not t['hit@3']],
            'mean_search_ms': round(sum(t['search_ms'] for t in ts) / n, 1),
        }
        out.setdefault(strategy, {})[split] = row
    return out
