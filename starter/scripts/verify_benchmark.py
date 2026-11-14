"""Verify benchmark gold evidence against the source PDFs BEFORE any retrieval run.

For each question:
  - schema fields present, split counts (>=15 dev / >=5 test), >=3 filter questions (>=1 test);
  - evidence_quote is found on the gold page (and on every alternative_gold page);
  - lists every OTHER page that also contains the quote (possible undocumented alternative gold).
Text: same PyMuPDF extraction + normalize_text as the pipeline (src/ingestion.py).
Matching: Unicode NFC + remove all whitespace (robust to line re-joining).
Run from starter/:  .venv/Scripts/python.exe scripts/verify_benchmark.py
"""
import json
import re
import sys
import unicodedata
from pathlib import Path


sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.ingestion import load_pdf  # noqa: E402
BENCH = ROOT.parent / 'benchmark' / 'questions.json'
REQUIRED = ['id', 'split', 'question', 'expected_answer', 'gold_source_id', 'gold_page', 'evidence_quote', 'filter']


def squash(text: str) -> str:
    return re.sub(r'\s+', '', unicodedata.normalize('NFC', text))


def main() -> None:
    manifest = json.loads((ROOT / 'data' / 'manifest.json').read_text(encoding='utf-8'))
    pages = {}  # (source_id, page) -> squashed text
    for src in manifest['sources']:
        for pg in load_pdf(ROOT / src['local_path'], src['source_id'], src['local_path']):
            pages[(src['source_id'], pg.page)] = squash(pg.text)
    counted = {(s['source_id'], p['page']) for s in manifest['sources'] for p in s['pages'] if p['counted']}

    qs = json.loads(BENCH.read_text(encoding='utf-8'))['questions']
    errors = []
    for q in qs:
        missing = [k for k in REQUIRED if k not in q]
        if missing:
            errors.append(f"{q.get('id')}: missing fields {missing}")
            continue
        golds = [(q['gold_source_id'], q['gold_page'])] + [(a['source_id'], a['page']) for a in q.get('alternative_gold', [])]
        ev = squash(q['evidence_quote'])
        status = []
        for g in golds:
            ok = ev in pages.get(g, '')
            status.append(f"{g[0]}:p{g[1]}={'OK' if ok else 'NOT FOUND'}")
            if not ok:
                errors.append(f"{q['id']}: evidence not found on {g}")
            if g not in counted:
                errors.append(f"{q['id']}: gold page {g} is not a counted content page")
        others = [k for k, t in pages.items() if ev in t and k not in golds]
        flt = q['filter'] or '-'
        print(f"{q['id']} [{q['split']:4}] filter={flt} | {' '.join(status)}"
              + (f" | ALSO FOUND ON {others}" if others else ''))
        if others:
            errors.append(f"{q['id']}: quote also on {others} — add to alternative_gold or make quote more specific")

    dev = [q for q in qs if q['split'] == 'dev']
    test = [q for q in qs if q['split'] == 'test']
    fdev = [q['id'] for q in dev if q['filter']]
    ftest = [q['id'] for q in test if q['filter']]
    print(f"\nTotal {len(qs)} | dev {len(dev)} | test {len(test)} | filter dev {fdev} | filter test {ftest}")
    if len(qs) < 20 or len(dev) < 15 or len(test) < 5:
        errors.append('need >=20 questions, >=15 dev, >=5 test')
    if len(fdev) + len(ftest) < 3 or not ftest:
        errors.append('need >=3 filter questions with >=1 in test')
    dev_pages = {(q['gold_source_id'], q['gold_page']) for q in dev}
    leak = [(q['id'], (q['gold_source_id'], q['gold_page'])) for q in test
            if (q['gold_source_id'], q['gold_page']) in dev_pages]
    print(f"Test primary-gold pages shared with dev: {leak or 'none'}")
    if errors:
        print('\nERRORS:\n  ' + '\n  '.join(errors))
        sys.exit(1)
    print('\nAll evidence verified.')


if __name__ == '__main__':
    main()
