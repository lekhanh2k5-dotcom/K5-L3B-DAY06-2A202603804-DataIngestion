"""Local labeling UI for results/audit/*.csv (stdlib only, binds to 127.0.0.1).

    .venv/Scripts/python.exe scripts/label_ui.py      -> opens http://127.0.0.1:8765

- One item per screen; keys: 0/1/2 (or Y/N) to label, <- / -> to navigate, R to focus reason.
- Every change is written straight back to the CSV (UTF-8 BOM, other columns untouched).
- Coherence: C uses the same chunk as B, so a B label is mirrored to C automatically.
- Metadata: the same chunk_id can appear for several strategies -> label once, mirrored.
- Blind mode (default ON for coherence/grounding): strategy name and score are hidden and
  items are shuffled with a fixed seed, to reduce bias from knowing Hit@k results.
- PDF pages are served from data/raw (only files listed in the manifest) to check sources.
"""
import csv
import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / 'results' / 'audit'
SHEETS = {
    'coherence': {'file': 'coherence.csv', 'label': 'label_0_1_2', 'note': 'reason'},
    'metadata': {'file': 'metadata.csv', 'label': 'human_metadata_complete_and_correct_Y_N', 'note': 'error_note'},
    'grounding': {'file': 'grounding.csv', 'label': 'label_0_1_2', 'note': 'reason'},
}
LOCK = threading.Lock()
manifest = json.loads((ROOT / 'data' / 'manifest.json').read_text(encoding='utf-8'))
PDFS = {s['source_id']: Path(s['local_path']).name for s in manifest['sources']}
ALLOWED_PDF = set(PDFS.values())


def load(sheet: str) -> tuple[list[str], list[dict]]:
    with (AUDIT / SHEETS[sheet]['file']).open(encoding='utf-8-sig', newline='') as f:
        r = csv.DictReader(f)
        return list(r.fieldnames), list(r)


DATA = {s: load(s) for s in SHEETS}


def save(sheet: str) -> None:
    fields, rows = DATA[sheet]
    path = AUDIT / SHEETS[sheet]['file']
    tmp = path.with_suffix('.tmp')
    with tmp.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def update(sheet: str, index: int, label: str, note: str) -> list[int]:
    cfg = SHEETS[sheet]
    rows = DATA[sheet][1]
    target = rows[index]
    if sheet == 'coherence':        # B <-> C share the chunk
        linked = [i for i, r in enumerate(rows) if r['position_id'] == target['position_id']
                  and r['chunk_id'] == target['chunk_id']]
    elif sheet == 'metadata':       # same chunk -> same metadata
        linked = [i for i, r in enumerate(rows) if r['chunk_id'] == target['chunk_id']]
    else:
        linked = [index]
    for i in linked:
        rows[i][cfg['label']] = label
        rows[i][cfg['note']] = note
    save(sheet)
    return linked


PAGE = r'''<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Chấm audit Day 06</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1d2433;--mute:#667085;--line:#e4e7ec;--acc:#2f6fed;--ok:#12805c;--warn:#b54708;--bad:#c4320a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,Segoe UI,sans-serif}
header{position:sticky;top:0;background:var(--card);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;z-index:2}
.tab{border:1px solid var(--line);background:#fff;border-radius:8px;padding:6px 12px;cursor:pointer}
.tab.on{background:var(--acc);color:#fff;border-color:var(--acc)}
.grow{flex:1}.mute{color:var(--mute)}.small{font-size:13px}
main{display:grid;grid-template-columns:220px 1fr;gap:16px;padding:16px;max-width:1300px;margin:auto}
#list{background:var(--card);border:1px solid var(--line);border-radius:10px;max-height:calc(100vh - 90px);overflow:auto;position:sticky;top:70px}
#list div{padding:6px 10px;border-bottom:1px solid var(--line);cursor:pointer;font-size:13px;display:flex;justify-content:space-between}
#list div.cur{background:#eaf1ff}#list .done{color:var(--ok);font-weight:600}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin-bottom:14px}
h2{margin:0 0 6px;font-size:18px}h3{margin:14px 0 6px;font-size:14px;color:var(--mute);text-transform:uppercase;letter-spacing:.03em}
.text{white-space:pre-wrap;background:#fbfcfd;border:1px solid var(--line);border-radius:8px;padding:12px;max-height:420px;overflow:auto}
.hit{display:grid;grid-template-columns:1fr;gap:10px}
.badge{display:inline-block;border-radius:6px;padding:1px 8px;font-size:12px;background:#eef2f6;margin-right:6px}
.b2008{background:#fff1e6;color:#9a3412}.b2024{background:#e7f6ee;color:#0f6b47}
.t{color:var(--ok)}.f{color:var(--bad)}
.labels{display:flex;gap:10px;flex-wrap:wrap;margin:10px 0}
.lab{flex:1;min-width:150px;border:2px solid var(--line);background:#fff;border-radius:10px;padding:10px;cursor:pointer;text-align:left}
.lab b{font-size:20px;margin-right:6px}.lab.on{border-color:var(--acc);background:#eaf1ff}
textarea{width:100%;min-height:60px;border:1px solid var(--line);border-radius:8px;padding:8px;font:inherit}
.nav{display:flex;gap:8px;align-items:center}button.n{border:1px solid var(--line);background:#fff;border-radius:8px;padding:8px 14px;cursor:pointer}
.saved{color:var(--ok);font-size:13px}kbd{border:1px solid var(--line);border-bottom-width:2px;border-radius:4px;padding:0 5px;font-size:12px;background:#fff}
a{color:var(--acc)}
@media(max-width:800px){main{grid-template-columns:1fr}#list{position:static;max-height:200px}}
</style></head><body>
<header><b>Chấm audit</b>
<button class="tab" data-s="coherence">1. Coherence</button>
<button class="tab" data-s="metadata">2. Metadata</button>
<button class="tab" data-s="grounding">3. Grounding</button>
<span class="grow"></span>
<label class="small"><input type="checkbox" id="blind"> Chế độ mù (ẩn tên chiến lược &amp; score)</label>
<span id="prog" class="small mute"></span></header>
<main><div id="list"></div><div id="view"></div></main>
<script>
const SCALE={
 coherence:[['0','Bị cắt giữa ý / thiếu chủ thể, không hiểu'],['1','Hiểu một phần, thiếu ngữ cảnh'],['2','Tự hiểu được, giữ trọn ý']],
 metadata:[['Y','source, page, law_year, Điều đủ và đúng'],['N','Thiếu hoặc sai (ghi lỗi bên dưới)']],
 grounding:[['0','Không có bằng chứng'],['1','Có nhưng thiếu điều kiện / ngữ cảnh / sai luật'],['2','Đủ để trả lời và truy được nguồn']]};
const HELP={coherence:'Đọc riêng chunk, KHÔNG nhìn trang gốc: chunk có tự hiểu được không?',
 metadata:'Mở PDF đúng trang, xác nhận source / page / law_year / Điều của chunk.',
 grounding:'Top-3 có đủ bằng chứng (kể cả điều kiện, ngoại lệ, đúng luật) để trả lời câu hỏi không?'};
let D,sheet='coherence',order={},pos={},blind=true;
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function rng(seed){return()=>{seed=(seed*1103515245+12345)%2147483648;return seed/2147483648}}
function buildOrder(){for(const s in D.sheets){const idx=D.sheets[s].rows.map((_,i)=>i);
  if(s!=='metadata'){const r=rng(42+s.length);for(let i=idx.length-1;i>0;i--){const j=Math.floor(r()*(i+1));[idx[i],idx[j]]=[idx[j],idx[i]]}}
  if(s==='coherence')order[s+'_blind']=idx.filter(i=>D.sheets[s].rows[i].strategy!=='C');
  order[s+'_blind']=order[s+'_blind']||idx;
  order[s]=D.sheets[s].rows.map((_,i)=>i).filter(i=>s!=='coherence'||D.sheets[s].rows[i].strategy!=='C');
  pos[s]=0}}
const ord=()=>order[sheet+(blind&&sheet!=='metadata'?'_blind':'')];
const row=i=>D.sheets[sheet].rows[i];const L=()=>D.sheets[sheet].label,N=()=>D.sheets[sheet].note;
function pdf(doc,page){const f=D.pdfs[doc];return f?`<a target="_blank" href="/pdf/${f}#page=${page}">mở PDF trang ${page} ↗</a>`:''}
function yr(y){return `<span class="badge b${y}">luật ${y}</span>`}
function tf(v){return v==='True'?'<b class="t">✔</b>':v==='False'?'<b class="f">✘</b>':'–'}
function title(r,k){return blind&&sheet!=='metadata'?`Mục ${k+1}`:`${r.strategy} · ${r.question_id||r.position_id}`}
function renderList(){const o=ord();$('#list').innerHTML=o.map((i,k)=>{const r=row(i);const v=r[L()];
  return `<div class="${k===pos[sheet]?'cur':''}" data-k="${k}"><span>${esc(title(r,k))}</span><span class="${v?'done':'mute'}">${v||'·'}</span></div>`}).join('');
  $('#list').querySelectorAll('div').forEach(d=>d.onclick=()=>{pos[sheet]=+d.dataset.k;render()});
  const done=o.filter(i=>row(i)[L()]).length;$('#prog').textContent=`${done}/${o.length} đã chấm`;
  const cur=$('#list .cur');if(cur)cur.scrollIntoView({block:'nearest'})}
function body(r){
 if(sheet==='coherence'){const [doc,p]=r.page_id.split(':p');
  return `<h3>Chunk cần chấm (${r.chunk_len} ký tự)</h3><div class="text">${esc(r.chunk_text)}</div>
  <details><summary class="small mute">Xem đoạn nguồn tại vị trí (chỉ để tham chiếu) · ${esc(r.page_id)} · ${pdf(doc,p)}</summary><div class="text small">${esc(r.position_paragraph)}</div></details>`}
 if(sheet==='metadata'){const f=r.question_filter?`<span class="badge">câu hỏi lọc: ${esc(r.question_filter)}</span>`:'';
  return `<p>${f}<span class="badge">rank ${r.rank}</span> <code>${esc(r.chunk_id)}</code></p>
  <table class="small"><tr><td>source</td><td><code>${esc(r.source)}</code></td></tr><tr><td>page</td><td><b>${r.page}</b> · ${pdf(r.document_id,r.page)}</td></tr>
  <tr><td>law_year</td><td>${yr(r.law_year)}</td></tr><tr><td>Điều</td><td><b>${esc(r.dieu)||'(trống)'}</b></td></tr></table>
  <h3>Kiểm tra tự động</h3><p class="small">text có trên trang ${tf(r.auto_text_found_on_page)} · law_year khớp manifest ${tf(r.auto_law_year_matches_manifest)} · Điều hợp lý ${tf(r.auto_dieu_plausible)} · tuân thủ filter ${tf(String(r.auto_respects_filter))}</p>
  <h3>Đầu chunk</h3><div class="text small">${esc(r.chunk_text_start)}…</div>`}
 const tops=[1,2,3].map(k=>{const t=r['top'+k]||'';const nl=t.indexOf('\n');let head=t.slice(0,nl),txt=t.slice(nl+1);
   const m=head.match(/\[(.+?) \| (\d{4}) \| Điều (.*?) \| score ([\d.]+)\]/)||[];const [, id,y,d,sc]=m;
   const doc=(id||'').split(':p')[0],pg=(id||'').split(':p')[1]?.split(':')[0];
   return `<div><p class="small"><b>Top ${k}</b> ${yr(y)} Điều ${esc(d)} · trang ${pg} · ${pdf(doc,pg)} ${blind?'':`· score ${sc}`}</p><div class="text small">${esc(txt)}</div></div>`}).join('');
 const f=r.question_filter?`<span class="badge">người dùng hỏi theo: ${esc(r.question_filter)}</span>`:'<span class="badge">không có filter</span>';
 return `<div class="card" style="background:#fbfcff"><h2>${esc(r.question)}</h2><p>${f}</p>
  <p><b>Đáp án mong đợi:</b> ${esc(r.expected_answer)}</p><p class="small"><b>Evidence gold</b> (${esc(r.gold)}): <i>${esc(r.evidence_quote)}</i></p></div><div class="hit">${tops}</div>`}
function render(){const o=ord();const k=pos[sheet];const i=o[k];const r=row(i);
 document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('on',t.dataset.s===sheet));
 const v=r[L()];const mirror=sheet==='coherence'?'<p class="small mute">Nhãn này cũng được ghi cho C (C dùng cùng chunk với B).</p>':sheet==='metadata'?'<p class="small mute">Nhãn áp dụng cho mọi dòng có cùng chunk_id.</p>':'';
 $('#view').innerHTML=`<div class="card"><div class="nav"><h2 class="grow">${esc(title(r,k))}</h2>
  <button class="n" id="prev">← Trước</button><span class="small mute">${k+1}/${o.length}</span><button class="n" id="next">Sau →</button></div>
  <p class="mute small">${HELP[sheet]}</p>${body(r)}
  <h3>Nhãn</h3><div class="labels">${SCALE[sheet].map(([c,t])=>`<button class="lab ${v===c?'on':''}" data-v="${c}"><b>${c}</b>${t}</button>`).join('')}</div>
  <textarea id="note" placeholder="Lý do / ghi lỗi (phím R để gõ)">${esc(r[N()])}</textarea>
  <p><span id="saved" class="saved"></span></p>${mirror}
  <p class="small mute"><kbd>${SCALE[sheet].map(x=>x[0]).join('</kbd>/<kbd>')}</kbd> chấm · <kbd>←</kbd><kbd>→</kbd> chuyển · <kbd>R</kbd> gõ lý do · <kbd>Esc</kbd> thoát ô lý do</p></div>`;
 $('#prev').onclick=()=>go(-1);$('#next').onclick=()=>go(1);
 document.querySelectorAll('.lab').forEach(b=>b.onclick=()=>setLabel(b.dataset.v));
 $('#note').onchange=()=>send(r[L()],$('#note').value);renderList()}
function go(d){const o=ord();pos[sheet]=Math.max(0,Math.min(o.length-1,pos[sheet]+d));render();scrollTo(0,0)}
async function send(label,note){const i=ord()[pos[sheet]];
 const res=await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sheet,index:i,label,note})});
 if(!res.ok){alert('Lưu thất bại: '+await res.text());return}
 const {linked}=await res.json();linked.forEach(j=>{D.sheets[sheet].rows[j][L()]=label;D.sheets[sheet].rows[j][N()]=note});
 renderList();const s=$('#saved');if(s)s.textContent='✔ đã lưu vào '+D.sheets[sheet].file}
async function setLabel(v){await send(v,$('#note').value);render()}
document.addEventListener('keydown',e=>{if(e.target.tagName==='TEXTAREA'){if(e.key==='Escape')e.target.blur();return}
 const k=e.key.toUpperCase();if(SCALE[sheet].some(x=>x[0]===k)){setLabel(k)}else if(e.key==='ArrowRight')go(1);else if(e.key==='ArrowLeft')go(-1);
 else if(k==='R'){e.preventDefault();$('#note').focus()}});
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{sheet=t.dataset.s;render()});
$('#blind').onchange=e=>{blind=e.target.checked;pos[sheet]=0;render()};
fetch('/api/data').then(r=>r.json()).then(d=>{D=d;$('#blind').checked=blind;buildOrder();render()});
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep console quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == '/':
            return self._send(200, PAGE.encode('utf-8'), 'text/html; charset=utf-8')
        if path == '/api/data':
            payload = {'pdfs': PDFS, 'sheets': {s: {'rows': DATA[s][1], 'label': c['label'], 'note': c['note'],
                                                    'file': c['file']} for s, c in SHEETS.items()}}
            return self._send(200, json.dumps(payload, ensure_ascii=False).encode('utf-8'), 'application/json')
        if path.startswith('/pdf/') and path[5:] in ALLOWED_PDF:
            return self._send(200, (ROOT / 'data' / 'raw' / path[5:]).read_bytes(), 'application/pdf')
        self._send(404, b'not found', 'text/plain')

    def do_POST(self):
        if urlparse(self.path).path != '/api/save':
            return self._send(404, b'not found', 'text/plain')
        try:
            req = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            sheet, idx = req['sheet'], int(req['index'])
            allowed = {'coherence': {'0', '1', '2', ''}, 'grounding': {'0', '1', '2', ''}, 'metadata': {'Y', 'N', ''}}
            if sheet not in SHEETS or req['label'] not in allowed[sheet] or not 0 <= idx < len(DATA[sheet][1]):
                raise ValueError('invalid request')
            with LOCK:
                linked = update(sheet, idx, req['label'], str(req.get('note', ''))[:2000])
        except Exception as exc:   # report to the page instead of silently failing
            return self._send(400, str(exc).encode('utf-8'), 'text/plain; charset=utf-8')
        self._send(200, json.dumps({'linked': linked}).encode(), 'application/json')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    port = 8765
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    url = f'http://127.0.0.1:{port}'
    print(f'Labeling UI: {url}  (Ctrl+C để dừng; nhãn được lưu ngay vào results/audit/*.csv)')
    if '--no-browser' not in sys.argv:
        webbrowser.open(url)
    server.serve_forever()
