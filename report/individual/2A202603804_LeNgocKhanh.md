# Báo cáo cá nhân — Day 6

Học viên: Lê Ngọc Khánh · MSSV 2A202603804 · Lớp L3B · Thời điểm chạy: 2026-11-14 (UTC+7)

Mọi số liệu dưới đây lấy từ file trong `starter/results/` (tổng hợp bằng `scripts/summarize_results.py` → `results/summary.json`). Tập test chỉ có 5 câu nên mọi so sánh trên test là minh họa, không phải kết luận tổng quát.

## Dữ liệu và pipeline

- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang.**
  - Corpus gồm hai văn bản luật giao thông đường bộ Việt Nam:
    - `luat-gtdb-2008`: Luật Giao thông đường bộ 23/2008/QH12, bản hợp nhất 15/VBHN-VPQH (2019), in trên Công báo số 729+730, tải từ sgu.edu.vn.
    - `luat-ttatgtdb-2024`: Luật Trật tự, an toàn giao thông đường bộ 36/2024/QH15, bản hợp nhất 55/VBHN-VPQH (2026), tải từ datafiles.chinhphu.vn.
  - Quyền sử dụng: văn bản quy phạm pháp luật không thuộc đối tượng bảo hộ quyền tác giả (Điều 15 Luật SHTT). Tài liệu công khai, không có dữ liệu cá nhân.
  - **Tổng 135 trang vật lý, 133 trang được tính là trang nội dung** (60 + 73).
  - Quy tắc tính trang: text sau trích xuất và chuẩn hóa phải có ≥ 200 ký tự và không bị đánh dấu lỗi.
  - Hai trang bị loại, đều có lý do: 2008 p61 là trang trống; 2024 p74 có text sai, mất dấu tiếng Việt.
  - Manifest gồm nguồn, URL, sha256, ngày truy cập, số ký tự từng trang: `starter/data/manifest.json`.
- **Chuẩn hóa, lỗi và giới hạn** (`src/ingestion.py`).
  - Bộ trích xuất: PyMuPDF 2.1. pypdf đã được thử trước nhưng chèn khoảng trắng vào giữa từ ("ngư ời", "đư ờng").
  - Các bước chuẩn hóa:
    - Unicode NFC.
    - Bỏ header chạy (dòng "CÔNG BÁO/Số…", số trang).
    - Tách 59 chú thích cuối trang (lịch sử sửa đổi) sang `metadata.footnotes` và xóa số chú thích trong thân bài, ví dụ "3.8 Khi chở" → "3. Khi chở". Regex có loại trừ để không xóa nhầm "QH15", "cm3", "kW".
    - Nối dòng bị ngắt thành đoạn, nhưng giữ ranh giới Chương / Điều / khoản / điểm.
  - Kiểm tra chất lượng: trang có tỷ lệ chữ có dấu < 5% bị đánh dấu `garbled`.
  - Log: `results/ingestion_log.json`.
  - **Giới hạn:**
    - Trang 74 của luật 2024 chứa phần cuối Điều 89 (quy định chuyển tiếp) nhưng không đọc được và không OCR. Benchmark không dùng phần này.
    - Nội dung chú thích không nằm trong text chunk.
    - Mỗi trang được xử lý độc lập, nên Điều kéo dài qua 2 trang bị tách.
- **Embedding, vector store, metric, lệnh chạy và chi phí.**
  - Embedding: OpenRouter, model `openai/text-embedding-3-small`, **1536 chiều**. Câu hỏi và chunk dùng cùng model, không thêm tiền tố. Lỗi API thì báo lỗi ngay, không fallback sang vector giả.
  - Vector store: **Chroma 1.5.9 PersistentClient** (lưu trên đĩa `starter/chroma_db/`), **cosine**, chỉ mục HNSW (tìm kiếm xấp xỉ), lọc bằng `where`.
  - Lý do không dùng PostgreSQL + pgvector của starter: máy không có Docker/WSL.
  - Lệnh chạy: xem `README.md`.
  - **Chi phí embedding index:** 259.941 token, **$0.0052**, theo `usage.cost` OpenRouter trả về. Câu hỏi: dev 612 token, test 190 token, gần như $0.
  - Thời gian: ingest 0,7 s; index A 22,95 s; index B 15,74 s; tìm kiếm trung bình 3–8 ms/câu.
- **Metadata bắt buộc, trường lọc, nguồn giá trị và lý do chọn.**
  - Mỗi chunk có `document_id`, `source` (đường dẫn PDF), `page` (số thứ tự trang trong file PDF), `chunk_id` ổn định, `char_start`/`char_end`.
  - **Trường lọc `law_year` (int: 2008 | 2024)** cùng `law_id`, lấy từ tiêu đề văn bản. Lý do chọn: hai luật quy định khác nhau về cùng một vấn đề (tuổi tối đa, chở 2 người, hạng bằng lái…), và người dùng thường biết mình hỏi luật nào.
  - Thêm `chuong`, `dieu`, `dieu_title`, tách bằng regex từ heading. Điều đang hiệu lực ở đầu trang được mang sang từ trang trước.
  - Không dùng "trạng thái hiệu lực" làm metadata, vì việc Luật 2008 hết hiệu lực không ghi trong file nguồn.

## Cấu hình và benchmark

- **A / B / C** (`starter/configs/strategies.json`):
  - **A:** `fixed_size` 500 ký tự, overlap 50, điểm cắt lùi về khoảng trắng. **629 chunk** (median 497 ký tự).
  - **B:** `by_paragraph`. Mỗi Chương/Điều mở chunk mới, gom khoản/điểm đến tối đa 1000 ký tự; khoản dài hơn thì cắt ở `; ` hoặc `. `; tiêu đề luôn đi cùng đoạn sau. **426 chunk** (median 646, max 1026).
  - **C:** dùng **cùng collection B**, thêm `where law_year = …` **chỉ cho câu có filter**.
  - **B–C chỉ khác nhau đúng một yếu tố là filter.** A–B chỉ khác cách chunk: cùng metadata, cùng model, không chèn tiêu đề vào text.
  - Chunk không vượt ranh giới trang, nên `page` luôn chính xác.
- **Benchmark** (`benchmark/questions.json`, phiên bản `v1-final`):
  - Gồm **20 câu: 15 dev / 5 test**, chia trước khi chạy thử.
  - Loại câu: trực tiếp (4), diễn đạt lại (5), có điều kiện/ngoại lệ (3), **có filter `law_year` (8: 5 dev, 3 test)**.
  - t04 có 2 trang gold hợp lệ (cả hai luật đều cấm nồng độ cồn).
  - Evidence được kiểm chứng tự động bằng `scripts/verify_benchmark.py` trên cùng text đã chuẩn hóa: 20/20 có mặt ở trang gold và không xuất hiện ở trang nào khác. Học viên đã đọc và xác nhận từng câu trước khi chốt.
  - Rủi ro rò rỉ: trang gold phụ của t04 (2024 p7) trùng trang gold của d14.
- **Tiêu chí chọn chiến lược đã chốt trước khi chạy:**
  1. dev Evidence Hit@3
  2. dev Hit@1
  3. grounding
  4. tài nguyên

  Khi chạy dev, B và C hòa ở bước 1, 2 và 4. Bước 3 lại chỉ chấm trên test. Vì vậy **sau khi xem dev, trước khi chạy test**, tôi bổ sung tie-break "dev filter compliance" (ghi trong `configs/strategies.json`). `src/run.py` không cho chạy test khi chưa có `results/selection.json`.

## Kết quả

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian (index) | Chi phí (embed) |
|---|---|---|---|---|---|---|
| A | dev | 8/15 | 10/15 | 629 | 22,95 s | $0.0027 |
| A | test | 0/5 | 1/5 | 629 | 22,95 s | $0.0027 |
| B | dev | 9/15 | 12/15 | 426 | 15,74 s | $0.0025 |
| B | test | 2/5 | 3/5 | 426 | 15,74 s | $0.0025 |
| C | dev | 9/15 | 12/15 | 426 (dùng chung B) | 0 (dùng chung B) | $0 thêm |
| C | test | 3/5 | 3/5 | 426 (dùng chung B) | 0 (dùng chung B) | $0 thêm |

Chỉ số chẩn đoán phụ, Page Hit@3 (đúng trang nhưng không cần trọn evidence): A dev 10/15, test **4/5**; B và C dev 12/15, test 3/5.

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 0,8 (10): 2 câu 0, 8 câu 1 | 15/15 | dev 0/5 · test 0/3 | 2 / 2 / 1 → **0,8** |
| B | 1,5 (10): 5 câu 1, 5 câu 2 | 15/15 | dev 1/5 · test 1/3 | 2 / 0 / 3 → **1,2** |
| C | 1,5 (10): như B, cùng chunk | 15/15 | dev **5/5** · test **3/3** | 2 / 0 / 3 → **1,2** |

**Đường dẫn trace, nhãn thủ công và cách chọn mẫu.**
- Trace top-3 đầy đủ (text, score, metadata, cờ hit): `results/traces_dev.jsonl`, `results/traces_test.jsonl`. Chỉ số: `results/metrics_*.json`.
- Nhãn chấm tay: `results/audit/{coherence,metadata,grounding}.csv`. Quy tắc chấm: `results/audit/README.md`.
- **Coherence:** 10 vị trí chọn theo quy tắc cố định, không phụ thuộc điểm số: trang thứ 6, 19, 32… trong danh sách trang đã sắp xếp, lấy đoạn chứa ký tự giữa trang. Kết quả là 5 trang mỗi luật.
- **Metadata:** 5 câu test × top-3 × 3 cấu hình. Đối chiếu với PDF, có kiểm tra tự động hỗ trợ.
- **Grounding:** 5 câu test × 3 cấu hình.
- **Người chấm:** tác giả bài (có nguy cơ thiên lệch vì đã biết Hit@k). Để giảm thiên lệch, tôi chấm bằng giao diện `scripts/label_ui.py` ở chế độ mù (ẩn tên chiến lược và score, xáo thứ tự cố định). Không dùng LLM để chấm.
- **Rà soát nhất quán sau khi chấm:** sửa 4 nhãn, mỗi chỗ đều được đánh dấu trong CSV:
  - t01/A: grounding 1 → 0, vì top-1 chỉ nhắc tên hạng B2, không có định nghĩa B2.
  - t03/B: grounding 1 → 0, để nhất quán với C (cùng chunk top-1).
  - pos09/B và C: coherence 2 → 1, vì thiếu tiêu đề Điều, nhất quán với pos04 và pos07.
  - t05/A: chỉ sửa lý do.

## Phân tích và kết luận

- **So sánh A–B (chỉ thay cách chunk).**
  - B hơn A ở mọi chỉ số:
    - Evidence Hit@3: dev 12/15 so với 10/15, test 3/5 so với 1/5.
    - Coherence: 1,5 so với 0,8.
    - Grounding: 1,2 so với 0,8.
  - B còn ít chunk hơn (426 so với 629) và tốn ít token hơn (A thừa khoảng 9% do overlap).
  - Bằng chứng rõ nhất: trên test, **A tìm đúng trang ở 4/5 câu nhưng chỉ 1/5 câu có chunk chứa trọn evidence.** Chunk 500 ký tự cắt ngang danh sách hạng bằng lái (t01, t02) và danh sách trường hợp dùng đèn chiếu gần (t05).
  - 8/10 chunk A trong mẫu coherence bắt đầu hoặc kết thúc giữa câu. B cũng có điểm yếu: chunk tiếp nối ở đầu trang không có tiêu đề Điều (pos04, pos07, pos09 được 1 điểm).
- **So sánh B–C (chỉ thay filter).**
  - Filter đưa tỷ lệ top-3 đúng luật từ 1/5 lên 5/5 (dev) và từ 1/3 lên 3/3 (test), Hit@1 test tăng từ 2/5 lên 3/5.
  - Ví dụ d04 (hỏi luật 2024): B xếp Điều 30 luật 2008 ở hạng 1, gold chỉ ở hạng 3; C đưa gold lên hạng 1.
  - Evidence Hit@3 và grounding **không đổi**. Filter chỉ sắp lại và loại bỏ chunk sai luật, không cứu được câu mà embedding tìm sai chỗ.
- **Hai ví dụ lỗi** (phân tích sau khi đã chốt kết quả, không dùng để chỉnh cấu hình):
  1. **t03, B và C** (`luat-ttatgtdb-2024`, gold p17, Điều 21 "Sử dụng tín hiệu còi"):
     - Top-1 là Điều 14 (vượt xe, trang 14). Chunk này trùng cụm "từ 22 giờ ngày hôm trước đến 05 giờ ngày hôm sau" nhưng nói về báo hiệu xin vượt. Đây là lỗi khớp theo từ khóa.
     - Chunk Điều 21 của B (514 ký tự, gồm cả khoản 1 "chỉ được sử dụng còi khi…") chỉ đứng **hạng 7**. Chunk 500 ký tự của A cắt gọn quanh khoản 2 nên lên hạng 2 (A grounding được 2).
     - Đây là ca duy nhất A hơn B: chunk nhỏ và tập trung có lợi khi câu hỏi nhắm vào một khoản cụ thể.
  2. **t04, cả A/B/C** (gold `luat-ttatgtdb-2024` p7 hoặc `luat-gtdb-2008` p10, "nồng độ cồn"):
     - Câu hỏi dùng từ đời thường *"uống rượu bia rồi lái xe"*, còn văn bản luật dùng *"trong máu hoặc hơi thở có nồng độ cồn"*.
     - Evidence nằm trong chunk Điều 9 (930 ký tự, liệt kê hơn 20 hành vi bị cấm). Chunk này chỉ đứng **hạng 10** ở B, nên tín hiệu bị loãng.
     - d14 (dùng điện thoại, cùng Điều 9) cũng trượt vì cùng nguyên nhân.
- **Chiến lược chọn, đánh đổi, điều kiện áp dụng.**
  - **Chọn C** (chunk theo cấu trúc + filter `law_year`).
  - Đánh đổi:
    - C cần người dùng hoặc ứng dụng cung cấp `law_year` trước khi truy xuất. Câu không có filter thì C hoạt động như B.
    - Nếu filter sai (người dùng chọn nhầm luật), C sẽ loại mất bằng chứng đúng.
    - Chunk B lớn hơn nên một chunk có thể chứa nhiều ý, làm loãng embedding (t03, t04).
  - Điều kiện áp dụng: corpus có nhiều phiên bản hoặc nhiều văn bản cùng chủ đề, và có metadata đáng tin để phân biệt.
- **Hạn chế.**
  - Test chỉ có 5 câu, nên chênh 1 câu là 20 điểm phần trăm. Tie-break được bổ sung sau khi xem dev.
  - Nhãn do một người chấm, và người chấm là tác giả bài.
  - Evidence match chặt (phải trọn đoạn trích trong một chunk), nên có thể đánh thấp các chunk đúng một phần. Chấm tay grounding được dùng để bù phần này.
  - Thời gian đo trên một máy, một lần chạy. Chi phí lấy từ OpenRouter.
  - Trang 74 của luật 2024 không được OCR. Chú thích cuối trang không nằm trong text chunk.
- **Nếu làm lại hoặc mở rộng:**
  - Chèn tiêu đề "Luật – Chương – Điều" vào đầu text chunk B, như một thí nghiệm riêng, để sửa chunk tiếp nối thiếu ngữ cảnh.
  - Giảm `max_size` của B, hoặc tách từng khoản thành một chunk, cho các Điều dạng danh sách dài (Điều 8, 9).
  - Thử hybrid BM25 + dense cho câu hỏi đời thường hoặc cần khớp số liệu.
  - Mở rộng tập test lên khoảng 20 câu, và có người chấm thứ hai để đo độ đồng thuận.

**Công cụ AI:** dùng Claude Code để hỗ trợ viết code, soạn nháp benchmark và báo cáo. Học viên đã tự xác minh evidence, chấm toàn bộ nhãn thủ công và rà soát số liệu với các file trong `results/`.
