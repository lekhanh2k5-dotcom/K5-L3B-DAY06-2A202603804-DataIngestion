# Audit thủ công — quy tắc chấm và thao tác trên file

Người chấm: tác giả bài (Lê Ngọc Khánh). Nguy cơ thiên lệch: người chấm đã biết kết quả Hit@k; giảm bớt bằng chế độ mù của `scripts/label_ui.py` (ẩn tên chiến lược + score, xáo thứ tự cố định). Không dùng LLM để chấm.

| File | Mục đích (tiêu chí GUIDE) | Số dòng | Cột cần điền | Giá trị hợp lệ |
|---|---|---|---|---|
| `coherence.csv` | §4.2 Chunk coherence: chunk đọc riêng có hiểu được không | 30 (10 vị trí × A/B/C) | `label_0_1_2`, `reason` | `0`, `1`, `2` |
| `metadata.csv` | §4.3 Metadata usefulness: metadata của kết quả top-3 có đủ và đúng không | 45 (5 câu test × top-3 × A/B/C) | `human_metadata_complete_and_correct_Y_N`, `error_note` | `Y`, `N` |
| `grounding.csv` | §4.4 Grounding: top-3 có đủ bằng chứng để trả lời và truy nguồn không | 15 (5 câu test × A/B/C) | `label_0_1_2`, `reason` | `0`, `1`, `2` |

## 1. coherence.csv

Đọc riêng `chunk_text`, không nhìn `position_paragraph` / trang gốc trước khi chấm.

| Tình huống | Nhãn |
|---|---|
| Có ngữ cảnh (heading Điều hoặc câu dẫn), mọi câu trọn vẹn; nếu bị cắt thì chỉ cắt **giữa hai điểm/khoản** | **2** (ghi "danh sách tiếp tục ở chunk sau" nếu có) |
| Bắt đầu bằng "đ) …", "3. …" **không có câu dẫn** → không biết đang liệt kê gì; hoặc thiếu ngữ cảnh nhưng mọi câu vẫn trọn | **1** |
| Bắt đầu/kết thúc **giữa câu** nhưng còn **ít nhất một ý trọn vẹn** đọc riêng hiểu được | **1** |
| Bắt đầu/kết thúc giữa câu và **không còn ý nào** trọn vẹn (mảnh cụt, thiếu chủ thể) | **0** |
| Phần mở đầu văn bản (quốc hiệu, căn cứ ban hành) đọc hiểu được | chấm như nội dung thường |

- Dòng `strategy = C` dùng **cùng chunk** với dòng B cùng `position_id` → nhãn và lý do **giống hệt B**.
- Vị trí được chọn theo quy tắc cố định (trang thứ 6, 19, 32… trong danh sách trang đã sắp xếp; đoạn chứa ký tự giữa trang), không phụ thuộc điểm số.

## 2. metadata.csv

Mở PDF đúng trang (`page` = **số thứ tự trang trong file PDF**, không phải số in ở góc trang Công báo), đối chiếu:

| Trường | Đúng khi |
|---|---|
| `page` | đoạn `chunk_text_start` nằm trên trang PDF đó |
| `source` / `document_id` / `law_year` | đúng file luật và đúng năm (2008 = Luật GTĐB, 2024 = Luật TTATGTĐB) |
| `dieu` | chunk thuộc Điều đó (kể cả phần tiếp của Điều từ trang trước); phần mở đầu văn bản để trống là đúng |

- Đúng hết → `Y`. Sai bất kỳ trường nào → `N` + `error_note` nêu trường sai và giá trị đúng (vd. "dieu ghi 33, thực tế 34").
- `auto_respects_filter = False` **không** làm metadata sai (đó là lỗi truy xuất, đo riêng ở tỷ lệ tuân thủ filter). Chỉ chấm metadata có đúng sự thật không.
- Cùng `chunk_id` xuất hiện nhiều dòng (B và C trùng chunk) → điền **cùng nhãn** cho mọi dòng đó.
- Các cột `auto_*` là kiểm tra máy (text có trên trang, law_year khớp manifest, Điều hợp lý); chỉ tham khảo, không thay việc nhìn PDF.

## 3. grounding.csv

Đọc `question`, `question_filter`, `expected_answer`, `evidence_quote`, rồi `top1..top3`.

| Tình huống | Nhãn |
|---|---|
| Ít nhất 1 chunk chứa **đủ** đáp án, gồm điều kiện/ngoại lệ ("trừ…", "khi…"), **đúng luật** được hỏi, truy được Điều/trang | **2** |
| Có nội dung đúng chỗ nhưng **thiếu một phần**: thiếu điều kiện/ngoại lệ, danh sách bị cắt, phải ghép nhiều chunk mới đủ | **1** |
| Không chunk nào trả lời được câu hỏi | **0** |
| Câu có filter mà top-3 chỉ có điều khoản **luật sai năm** với nội dung khác luật được hỏi | **0** |

Ca đặc biệt:
- Chunk đúng ở top-3 nhưng top-1 là luật sai năm → vẫn **2**, ghi "top-1 là luật 20xx, dễ gây nhầm".
- `t04` (nồng độ cồn) không có filter, hai luật đều cấm → chunk luật nào cũng tính.
- Nội dung trả lời đúng nhưng nằm ở trang khác `gold` → vẫn tính, ghi "đúng nội dung, khác trang gold".
- Không trừ điểm vì chunk thừa/không liên quan; chỉ xét có đủ bằng chứng hay không.
- Đây là đánh giá **bằng chứng truy xuất**, không phải độ chính xác câu trả lời LLM. `auto_evidence_hit@3_proxy` chỉ tham khảo.

## Thao tác trên file

**Cách khuyến nghị — giao diện:** `.venv/Scripts/python.exe scripts/label_ui.py` → trình duyệt `http://127.0.0.1:8765`. Tự lưu từng nhãn vào CSV, tự chép nhãn B→C (coherence) và theo `chunk_id` (metadata).

**Nếu sửa trực tiếp bằng Excel:**
1. Mở file `.csv` bằng Excel (tiếng Việt hiển thị đúng vì file có BOM UTF-8).
2. Chỉ gõ vào các cột nhãn/lý do ở bảng trên; **không** xóa, đổi tên, chèn cột, đổi thứ tự dòng hay sửa nội dung cột khác.
3. Nhãn gõ đúng giá trị hợp lệ (`0/1/2`, `Y/N` viết hoa), không có khoảng trắng thừa.
4. Lưu: **File → Save As → "CSV UTF-8 (Comma delimited) (*.csv)"**, giữ nguyên tên file. Không lưu dạng `.xlsx`, không chọn "CSV (Comma delimited)" thường (mất dấu tiếng Việt).
5. **Đóng Excel** trước khi mở giao diện chấm hoặc báo tổng hợp — Excel khóa file, giao diện sẽ không lưu được.

**Không** chạy lại `scripts/make_audit.py` sau khi đã chấm: script tạo lại file và **xóa toàn bộ nhãn**. Nên sao lưu thư mục `results/audit/` sau khi chấm xong.

**Kiểm tra trước khi báo xong:** mọi dòng có nhãn hợp lệ (coherence 30/30, metadata 45/45, grounding 15/15); dòng C trong coherence giống B; mọi nhãn `N`/`0`/`1` có lý do.
