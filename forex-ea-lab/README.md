# forex-ea-lab — Backtest trung thực + 2 EA

Mục tiêu: kiểm chứng bằng dữ liệu thật xem 2 nhóm chiến lược SL/TP có sống nổi
qua chi phí giao dịch retail không, rồi đóng gói thành EA MQL5 để forward-test.
**Không tối ưu tham số** — mọi tham số chọn trước theo nguyên tắc, mọi kết quả
(kể cả lỗ) đều được báo cáo đầy đủ.

## Dữ liệu

| File | Nguồn | Phạm vi |
|---|---|---|
| `data/XAU_15m_data.csv.gz` | github.com/BaseMax/XAUUSD-LSTM | 2004-06 → 2025-09, M15 |
| `data/*h1.csv.gz` (8 cặp FX) | github.com/ejtraderLabs/historical-data | 2012-11 → 2022-03, H1 |

Giờ server = chuẩn MT (GMT+2/+3 theo DST Mỹ): vàng mở 01:00 thứ 2, đóng ~23:45
thứ 6. Phiên: Á 01-10h, London 10-18h, NY 15-23h (giờ server).

## Phát hiện 1 — Cấu trúc phiên của vàng đã thay đổi (2024-2025)

`scripts/session_analysis.py` → `results/session_analysis.txt`

- Median range phiên Á 2025 = **$23.6**, gần gấp đôi 2024 ($13.7) và gấp 3-4 lần
  2012-2019 ($5-9). Tỷ lệ Á/London từ ~45% lịch sử lên **82%**.
- Net move phiên Á 2025 ($10.1) ≈ London ($11.1) — lần đầu trong 21 năm.
- Mô hình sách vở "Á tích lũy → London bung" đã yếu đi rõ rệt từ 2024.

## Phát hiện 2 — Session breakout XAUUSD (spread 28 point + slippage)

`scripts/bt_xau_breakout.py` → `results/xau_breakout.txt`
Rule: box phiên → stop order 2 chiều (OCO) + buffer, SL = mép box đối diện,
TP = 2R, đóng cuối ngày, risk 1%/lệnh, vốn $20k.

| Config | PF | CAGR | maxDD |
|---|---|---|---|
| LondonBO (box Á 01-08, đánh 08-14) | 1.02 | +1.6% | -46% |
| NYBO (box London 10-15, đánh 15-21) | 0.97 | -2.4% | -65% |
| **AsiaBO (box 18-23 hôm trước, đánh phiên Á 01-08)** | 1.04 | +3.1% | -44% |
| **AsiaBO + filter trend D1 SMA50** | **1.08** | +2.8% | **-33%** |

AsiaBO+D1trend dương 4 năm liên tiếp 2022-2025 (+4.2k/+1.9k/+1.2k/+7.4k),
khớp với thay đổi cấu trúc phiên Á. **Edge mỏng** — không phải máy in tiền.

## Phát hiện 3 — Mean reversion BB+RSI+ADX H1: KHÔNG sống nổi qua chi phí

`scripts/bt_eurgbp_meanrev.py`, `scripts/bt_meanrev_sweep.py`
→ `results/eurgbp_meanrev.txt`, `results/meanrev_sweep.txt`

Cùng một bộ rule chạy trên 8 cặp (2012-2022, spread thực tế từng cặp):
**6/8 cặp lỗ** (EURGBP PF 0.78, EURCHF 0.59), USDCAD hòa (1.03), USDCHF dương
(1.14 — 1/8 mẫu dương rất có thể do may mắn chọn mẫu). Kết luận: nhóm chiến
lược này sau chi phí retail không có edge bền.

## EA (MQL5)

| File | Chart | Trạng thái |
|---|---|---|
| `ea/XAU_SessionBreakout.mq5` | XAUUSD M15 | Theo config AsiaBO+D1trend (đổi được phiên qua input). Edge mỏng — demo trước. |
| `ea/MeanReversionBB.mq5` | FX H1 | Backtest THẤT BẠI trên đa số cặp. Chỉ dùng forward-test demo / tham khảo khung code. |

Cả hai: risk cố định %/lệnh theo khoảng SL, chặn spread giãn, không martingale,
không grid, không DCA. Lưu ý khi backtest trên MT5 dùng "Every tick based on
real ticks" và spread thật.

## Giới hạn của nghiên cứu này

- Dữ liệu 1 nguồn/khung M15-H1, chưa mô phỏng spread giãn theo giờ & swap.
- Slippage giả định cố định ($0.07 vàng / 0.2 pip FX).
- Không walk-forward từng tham số (vì không tối ưu tham số nào).
- Kết quả quá khứ không bảo đảm tương lai; AsiaBO hưởng lợi từ regime
  2022-2025, regime có thể đổi.

## Chạy lại

```bash
pip install pandas numpy
cd forex-ea-lab
python3 scripts/session_analysis.py
python3 scripts/bt_xau_breakout.py
python3 scripts/bt_eurgbp_meanrev.py
python3 scripts/bt_meanrev_sweep.py
```
