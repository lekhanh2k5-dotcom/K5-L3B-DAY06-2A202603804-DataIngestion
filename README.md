# Day 06 · Data Ingestion Engineering — Lê Ngọc Khánh (2A202603804, L3B)

Kho tri thức truy xuất được cho **Luật Giao thông đường bộ 2008** và **Luật Trật tự, an toàn giao thông đường bộ 2024** (133 trang nội dung), so sánh 3 chiến lược dữ liệu A/B/C trên 20 câu hỏi (15 dev / 5 test).

- Báo cáo: [report/individual/2A202603804_LeNgocKhanh.md](report/individual/2A202603804_LeNgocKhanh.md)
- Đề bài gốc: [docs/LAB_README.md](docs/LAB_README.md) · thông tin học viên: [STUDENT.md](STUDENT.md)

| | Lựa chọn |
|---|---|
| Đọc PDF | PyMuPDF 2.1 (pypdf chèn khoảng trắng giữa từ tiếng Việt) |
| Embedding | OpenRouter `openai/text-embedding-3-small`, 1536 chiều |
| Vector store | Chroma 1.5.9 PersistentClient, cosine (HNSW) — thay pgvector vì máy không có Docker |
| A | chunk cố định 500 ký tự, overlap 50 |
| B | chunk theo Chương/Điều/khoản, tối đa 1000 ký tự |
| C | chunk B + filter `law_year` khi câu hỏi có filter (**được chọn trên dev**) |

## Kết quả chính

| Strategy | Dev Hit@1 | Dev EvHit@3 | Test Hit@1 | Test EvHit@3 | Filter (dev · test) | Coherence /2 | Grounding /2 |
|---|---|---|---|---|---|---|---|
| A | 8/15 | 10/15 | 0/5 | 1/5 | 0/5 · 0/3 | 0,8 | 0,8 |
| B | 9/15 | 12/15 | 2/5 | 3/5 | 1/5 · 1/3 | 1,5 | 1,2 |
| C | 9/15 | 12/15 | 3/5 | 3/5 | 5/5 · 3/3 | 1,5 | 1,2 |

Chi phí embedding toàn bộ: 259.941 token ≈ **$0.0052**. Test chỉ 5 câu → minh họa, không kết luận tổng quát.

## Cấu trúc

```text
STUDENT.md · README.md · artifacts/experiment_log.csv · report/individual/2A202603804_LeNgocKhanh.md
benchmark/questions.json            # 20 câu, split, gold page, evidence (v1-final)
starter/
├── .env.example                    # copy -> .env, điền OPENROUTER_API_KEY
├── requirements.txt
├── configs/strategies.json         # tham số A/B/C, model, store, tiêu chí chọn (đã chốt)
├── data/manifest.json              # nguồn, URL, sha256, quyền, trang tính/loại + lý do
├── data/raw/*.pdf                  # 2 văn bản luật (công khai)
├── src/                            # ingestion, chunking, embeddings, store, index, evaluation, run
├── scripts/                        # check setup, manifest, verify benchmark, audit, label UI, summary
└── results/                        # pages, chunks, index/ingestion log, traces, metrics, selection,
    └── audit/                      #   summary + nhãn chấm tay (CSV) và quy tắc chấm
```

## Cài đặt

Python 3.11–3.14 (đã chạy với 3.12.10), Windows PowerShell:

```powershell
cd starter
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env          # rồi điền OPENROUTER_API_KEY trong .env (không commit)
.\.venv\Scripts\python.exe scripts\check_setup_chroma.py   # kiểm tra Chroma + 1 lần gọi embedding thật
```

macOS/Linux: `python3 -m venv .venv && source .venv/bin/activate`, sau đó dùng `python` thay cho `.\.venv\Scripts\python.exe`.

## Chạy lại toàn bộ (từ thư mục `starter/`)

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py scripts\build_manifest.py      # manifest + quy tắc tính trang (133 trang)
& $py scripts\verify_benchmark.py    # kiểm chứng 20 evidence trên text đã chuẩn hóa
& $py -m src.ingestion               # -> results/pages.jsonl, ingestion_log.json
& $py -m src.chunking                # -> results/chunks_A/B.jsonl, chunk_stats.json
& $py -m src.index                   # embed + lưu Chroma (~$0.005); chạy 2 lần sync để kiểm tra không nhân đôi
& $py scripts\check_store.py         # kiểm tra xử lý tài liệu thay đổi + filter (câu ngoài benchmark)
& $py -m src.run --split dev         # A/B/C trên dev -> traces, metrics, results/selection.json
& $py -m src.run --split test        # chỉ chạy được sau khi có selection.json
& $py scripts\summarize_results.py   # gộp chỉ số + nhãn chấm tay -> results/summary.json
```

Chấm tay: `scripts/make_audit.py` tạo `results/audit/*.csv` (**chạy lại sẽ xóa nhãn**), `scripts/label_ui.py` mở giao diện chấm tại `http://127.0.0.1:8765`. Quy tắc: [starter/results/audit/README.md](starter/results/audit/README.md).

`starter/chroma_db/` không được commit (dữ liệu tạo lại bằng `python -m src.index`). Kết quả embedding có thể lệch rất nhỏ giữa các lần gọi API; trace đã chạy nằm trong `starter/results/`.

## Ghi chú trung thực

- Tie-break "filter compliance" giữa B và C được bổ sung **sau khi xem dev, trước khi chạy test** (ghi trong `configs/strategies.json`).
- Người chấm tay là tác giả; đã chấm ở chế độ mù và rà soát nhất quán 4 nhãn sau chấm (đánh dấu trong CSV).
- Trang 74 luật 2024 (cuối Điều 89) không đọc được, không OCR; chú thích cuối trang không nằm trong text chunk.
- Dùng Claude Code hỗ trợ code/nháp; evidence và nhãn do học viên xác minh.
