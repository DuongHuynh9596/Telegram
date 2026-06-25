import json, os, logging, time, math
from datetime import datetime
from config import (SIGNAL_FILE, RISK_PCT, FIXED_SL_USD, FIXED_TP_USD,
                    BE_TRIGGER, CRASH_TRIG_ATR, CRASH_ATR_MULT, CRASH_LOOKBACK,
                    MIN_RR, TRAIL_TRIGGER, TRAIL_LOCK_USD, MAX_LOT, MAX_SL_CENT,
                    PRIMARY_TF, MIN_CONFLUENCE, CONFLUENCE_TOL,
                    ALLOW_UNFRESH_LEVELS, MAX_LEVEL_TOUCHES,
                    TRAIL_PH1_TRIGGER, TRAIL_PH1_LOCK,
                    TRAIL_PH2_TRIGGER, TRAIL_PH2_LOCK,
                    TRAIL_PH3_TRIGGER, TRAIL_PH3_LOCK,
                    ATR_PERIOD, ATR_TRAIL_X,
                    # v3.0
                    USE_STORYLINE, STORYLINE_HARD_FILTER,
                    COUNTER_BIAS_ALLOW, COUNTER_BIAS_MIN_CONF,
                    COUNTER_BIAS_REQUIRE_REJECTION, COUNTER_BIAS_REQUIRE_PREMIUM,
                    COUNTER_BIAS_REQUIRE_ROADBLOCK,
                    USE_QM, QM_TOL, USE_411, SETUP411_TOL,
                    USE_ROADBLOCK, USE_REJECTION,
                    ENTRY_MODE, LIMIT_APPROACH_TOL, LIMIT_MIN_DISTANCE,
                    LIMIT_ZONE_OFFSET, CONFIRM_MAX_CHASE,
                    PENDING_EXPIRY_SEC,
                    USE_ANTI_EXTREME, ANTI_EXT_LOOKBACK, ANTI_EXT_THRESH,
                    ANTI_EXT_STREAK)
from entry_models import detect_qm, detect_411
from rejection import detect_rejection

log = logging.getLogger('MSNR.Signal')


def calc_lot(balance):
    # FLOOR theo step 0.01 -> risk thuc KHONG vuot RISK_PCT% (dam bao <1%/lenh).
    # Voi SL distance dung $12 (enforce_fixed_risk ben main.py), risk = SL$ x lot x 100.
    # TRAN CUNG: lo/lenh <= MAX_SL_CENT cent -> cap lot (du balance to van khong vuot).
    risk_usd = balance * RISK_PCT / 100
    raw      = risk_usd / (FIXED_SL_USD * 100)
    cap      = MAX_SL_CENT / (FIXED_SL_USD * 100)   # tran tien lo (cent)
    lot      = math.floor(min(raw, cap) / 0.01) * 0.01
    return round(min(max(lot, 0.01), MAX_LOT), 2)


def _collect_nearby_levels(detector, center_price, tf, n=6):
    levels = detector.get_valid_levels(MAX_LEVEL_TOUCHES)
    sorted_levels = sorted(levels, key=lambda l: abs(l.price - center_price))
    result = []
    for lv in sorted_levels[:n]:
        t = lv.level_type[0] if lv.level_type[0] in ('A', 'V') else 'G'
        result.append({'t': t, 'p': round(lv.price, 2),
                       'tf': tf, 'fresh': lv.state == 'FRESH'})
    return result


def _flat_levels(nearby):
    """Convert list to flat keys lv0_t, lv0_p, lv1_t, ... for EA parsing"""
    d = {'lv_cnt': len(nearby)}
    for i, lv in enumerate(nearby):
        d[f'lv{i}_t'] = lv['t']
        d[f'lv{i}_p'] = lv['p']
    return d


class SignalGenerator:
    def __init__(self, detector, tl_engine, current_price, balance, storyline=None, tf=PRIMARY_TF):
        self.detector  = detector
        self.tl_engine = tl_engine
        self.price     = current_price
        self.balance   = balance
        self.lot       = calc_lot(balance)
        self.storyline = storyline
        self.df        = detector.df
        self.tf        = tf        # khung entry hien tai (H1/M30/M15)

        # Entry models (tính 1 lần / cycle)
        if USE_QM:
            highs, lows = detector.swings()
            self.qm_setups = detect_qm(self.df, highs, lows, current_price, QM_TOL)
        else:
            self.qm_setups = []
        self.setup411 = (detect_411(detector.levels, current_price, SETUP411_TOL)
                         if USE_411 else None)

    # ─────────────────────────────────────────────────────────────────────────
    def _levels_pool(self):
        """Level dùng làm confluence: FRESH + UNFRESH chạm ít (nếu cho phép)"""
        if ALLOW_UNFRESH_LEVELS:
            return self.detector.get_valid_levels(MAX_LEVEL_TOUCHES)
        return self.detector.get_fresh_levels()

    def generate(self, trendlines):
        pool = self._levels_pool()
        for action in ('SELL', 'BUY'):
            sig = self._build_signal(action, trendlines, pool)
            if sig:
                return sig
        return None

    def _tp(self, action, ref):
        if action == 'SELL':
            min_tp = ref - FIXED_SL_USD * MIN_RR
            v = sorted([l for l in self._levels_pool()
                        if l.level_type in ('V', 'GAP_S') and l.price < min_tp],
                       key=lambda l: l.price, reverse=True)
            return round(v[0].price, 2) if v else round(min_tp, 2)
        else:
            min_tp = ref + FIXED_SL_USD * MIN_RR
            a = sorted([l for l in self._levels_pool()
                        if l.level_type in ('A', 'GAP_R') and l.price > min_tp],
                       key=lambda l: l.price)
            return round(a[0].price, 2) if a else round(min_tp, 2)

    # ─────────────────────────────────────────────────────────────────────────
    def _limit_px(self, action, level_price):
        """Limit lùi NHẸ vào trong level (đón râu quét) → fill giá đẹp hơn."""
        if action == 'BUY':
            return round(level_price - LIMIT_ZONE_OFFSET, 2)   # support: chờ giá thụt xuống dưới level
        return round(level_price + LIMIT_ZONE_OFFSET, 2)        # resistance: chờ giá với lên trên level

    def _decide_entry(self, action, level_price, confirmed_ok, premium):
        """
        Quyết định loại entry theo ENTRY_MODE + trạng thái hiện tại.
        - CONFIRMED→MARKET: chỉ khi giá còn gần level (≤ CONFIRM_MAX_CHASE) → KHÔNG đuổi giá.
        - LIMIT: đặt lùi vào trong zone (level ∓ LIMIT_ZONE_OFFSET) để đón râu quét.
        Trả về (entry_type, order_type, entry_price) hoặc (None, None, None).
        """
        price = self.price
        # Limit hợp lệ: phải nằm ĐÚNG PHÍA + cách giá [MIN_DISTANCE .. APPROACH_TOL]
        if action == 'BUY':
            dist = price - level_price       # >0: level dưới giá → BuyLimit hợp lệ
        else:
            dist = level_price - price       # >0: level trên giá → SellLimit hợp lệ
        limit_ok    = (premium and LIMIT_MIN_DISTANCE <= dist <= LIMIT_APPROACH_TOL)
        market_ok   = (confirmed_ok and abs(price - level_price) <= CONFIRM_MAX_CHASE)
        limit_entry = self._limit_px(action, level_price)

        if ENTRY_MODE == 'CONFIRMED':
            if market_ok:
                return 'CONFIRMED', 'MARKET', round(price, 2)
            return None, None, None

        if ENTRY_MODE == 'LIMIT':
            if limit_ok:
                return 'LIMIT', 'LIMIT', limit_entry
            return None, None, None

        # BOTH: ưu tiên CONFIRMED gần level (market) > LIMIT đón râu.
        # Có rejection nhưng giá đã chạy xa (chase > ngưỡng) → KHÔNG đuổi, hạ xuống đặt LIMIT.
        if market_ok:
            return 'CONFIRMED', 'MARKET', round(price, 2)
        if limit_ok:
            return 'LIMIT', 'LIMIT', limit_entry
        return None, None, None

    def _overextended(self, action):
        """
        Entry xau: SELL khi gia sat DAY range gan day (hoac chuoi nen do dai),
        BUY khi gia sat DINH (hoac chuoi nen xanh dai) -> ne ra.
        """
        df = self.df
        n  = ANTI_EXT_LOOKBACK
        if len(df) < n + 2:
            return False
        highs  = df['high'].values
        lows   = df['low'].values
        opens  = df['open'].values
        closes = df['close'].values

        # 1) Vi tri gia trong range gan day (0=day, 1=dinh)
        hi = highs[-n:].max(); lo = lows[-n:].min(); rng = hi - lo
        pos = (self.price - lo) / rng if rng > 0 else 0.5
        if action == 'SELL' and pos < ANTI_EXT_THRESH:
            return True
        if action == 'BUY' and pos > (1 - ANTI_EXT_THRESH):
            return True

        # 2) Chuoi nen cung mau (momentum da duoi suc) — tu nen da dong gan nhat lui ve
        streak = 0
        for i in range(len(df) - 2, -1, -1):
            red   = closes[i] < opens[i]
            green = closes[i] > opens[i]
            if action == 'SELL' and red:
                streak += 1
            elif action == 'BUY' and green:
                streak += 1
            else:
                break
            if streak >= ANTI_EXT_STREAK:
                return True
        return False

    def _build_signal(self, action, trendlines, pool):
        is_sell  = (action == 'SELL')
        tol      = CONFLUENCE_TOL
        last_idx = len(self.df) - 1
        price    = self.price

        # ── 1. Storyline filter: chặn lệnh ngược khung lớn (TRỪ setup mạnh) ──
        is_counter = False
        if USE_STORYLINE and self.storyline and STORYLINE_HARD_FILTER:
            if not self.storyline.allows(action):
                if not COUNTER_BIAS_ALLOW:
                    return None
                is_counter = True   # ngược bias: chỉ cho khi hội đủ điều kiện mạnh (xét ở 5b)

        # ── 1b. Anti-extreme: ne SELL day / BUY dinh (entry xau) ──
        if USE_ANTI_EXTREME and self._overextended(action):
            return None

        tl_dir   = 'DOWN' if is_sell else 'UP'
        lv_type  = 'A'     if is_sell else 'V'
        gap_type = 'GAP_R' if is_sell else 'GAP_S'

        # ── 2. Các nguồn confluence quanh giá ──
        p3 = sorted([t for t in trendlines if t.direction == tl_dir
                     and abs(t.price_at(last_idx) - price) <= tol],
                    key=lambda t: abs(t.price_at(last_idx) - price))
        lv = sorted([l for l in pool if l.level_type == lv_type
                     and abs(l.price - price) <= tol],
                    key=lambda l: (l.state != 'FRESH', abs(l.price - price)))
        gap = sorted([l for l in pool if l.level_type == gap_type
                      and abs(l.price - price) <= tol],
                     key=lambda l: abs(l.price - price))
        qm = [q for q in self.qm_setups if q.direction == action]

        rb_hit  = bool(USE_ROADBLOCK and self.storyline
                       and self.storyline.at_roadblock(price))
        miss_lv = [l for l in lv if l.is_miss] + [l for l in gap if l.is_miss]
        s411 = (self.setup411 if (self.setup411 and self.setup411.matches(action))
                else None)

        # ── 3. Anchor: Trendline P3 HOẶC QM (MSNR: QM là entry model độc lập) ──
        if not (p3 or qm):
            return None

        n_conf = (sum(bool(x) for x in (p3, lv, gap, qm))
                  + (1 if rb_hit else 0) + (1 if s411 else 0))
        if n_conf < MIN_CONFLUENCE:
            return None

        # ── 4. Level neo (nơi limit nghỉ / nơi rejection xảy ra) ──
        if lv:
            level_price = lv[0].price
        elif qm:
            level_price = qm[0].entry
        elif gap:
            level_price = gap[0].price
        else:
            level_price = round(p3[0].price_at(last_idx), 2)

        # ── 5. Rejection confirm + quyết định loại entry ──
        rej = detect_rejection(self.df, level_price, action) if USE_REJECTION else None
        confirmed_ok = (rej is not None) if USE_REJECTION else (abs(price - level_price) <= tol)
        premium = bool(qm) or bool(miss_lv) or (lv and lv[0].state == 'FRESH')

        # ── 5b. Cổng NGƯỢC BIAS: chỉ cho lệnh ngược storyline khi setup mạnh ──
        if is_counter:
            strong = (n_conf >= COUNTER_BIAS_MIN_CONF
                      and (confirmed_ok or not COUNTER_BIAS_REQUIRE_REJECTION)
                      and (premium     or not COUNTER_BIAS_REQUIRE_PREMIUM)
                      and (rb_hit      or not COUNTER_BIAS_REQUIRE_ROADBLOCK))
            if not strong:
                return None

        entry_type, order_type, entry_px = self._decide_entry(
            action, level_price, confirmed_ok, premium)
        if entry_type is None:
            return None

        # ── 6. SL / TP / RR — CO DINH: SL $12, TP $10 → RR 0.83 ──
        if is_sell:
            sl = round(entry_px + FIXED_SL_USD, 2)
            tp = round(entry_px - FIXED_TP_USD, 2)
        else:
            sl = round(entry_px - FIXED_SL_USD, 2)
            tp = round(entry_px + FIXED_TP_USD, 2)
        rr = round(FIXED_TP_USD / FIXED_SL_USD, 2)
        if rr < MIN_RR:
            return None

        qm_apex = round(qm[0].apex, 2) if qm else 0.0
        entry_model = '+'.join([m for m, on in
                                (('QM', bool(qm)), ('TL', bool(p3)), ('411', bool(s411)))
                                if on]) or 'Level'

        nearby = _collect_nearby_levels(self.detector, price, self.tf)
        signal = {
            'action': action, 'entry': entry_px, 'sl': sl, 'tp': tp,
            'lot': self.lot, 'sl_usd': FIXED_SL_USD, 'tp_usd': FIXED_TP_USD,
            'be_trigger': BE_TRIGGER, 'crash_trig_atr': CRASH_TRIG_ATR,
            'crash_atr_mult': CRASH_ATR_MULT, 'crash_lookback': CRASH_LOOKBACK,
            'order_type': order_type, 'entry_type': entry_type,
            'entry_tf': self.tf,
            'pending_expiry': PENDING_EXPIRY_SEC,
            'entry_model': entry_model, 'qm_apex': qm_apex,
            'storyline_dir': self.storyline.direction if self.storyline else 'NEUTRAL',
            'storyline_origin': (self.storyline.origin_tf or '-') if self.storyline else '-',
            'roadblock': rb_hit, 'miss': bool(miss_lv), 'rejection': rej is not None,
            'counter_bias': is_counter,
            'trail_trigger': TRAIL_TRIGGER, 'trail_lock_usd': TRAIL_LOCK_USD,
            'trail_ph1_trigger': TRAIL_PH1_TRIGGER, 'trail_ph1_lock': TRAIL_PH1_LOCK,
            'trail_ph2_trigger': TRAIL_PH2_TRIGGER, 'trail_ph2_lock': TRAIL_PH2_LOCK,
            'trail_ph3_trigger': TRAIL_PH3_TRIGGER, 'trail_ph3_lock': TRAIL_PH3_LOCK,
            'atr_period': ATR_PERIOD, 'atr_x': ATR_TRAIL_X,
            'rr': rr, 'confluence': n_conf,
            'p3_trendline': bool(p3), 'fresh_level': bool(lv), 'gap_snr': bool(gap),
            'nearby_levels': nearby, 'timestamp': datetime.utcnow().isoformat(),
            'status': 'PENDING',
        }
        if p3 and not p3[0].p3_price:
            p3[0].p3_price = round(p3[0].price_at(last_idx), 2)
        if p3:
            signal['tl_dir'] = p3[0].direction
            signal['tl_p3']  = p3[0].p3_price
        signal.update(_flat_levels(nearby))
        self._build_analysis(signal, action, p3, lv, gap, qm, rej, rb_hit,
                             miss_lv, entry_type, entry_px, tp)
        return signal

    # ─────────────────────────────────────────────────────────────────────────
    def _build_analysis(self, signal, action, p3, lv, gap, qm, rej, rb_hit,
                        miss_lv, entry_type, entry, tp):
        tf = self.tf
        items = []

        # 0. Storyline (hướng khung lớn)
        if self.storyline:
            d = self.storyline.direction
            icon = '🧭'
            items.append({
                'icon': icon,
                'text': f'Storyline <b>{d}</b> (origin {self.storyline.origin_tf or "-"})',
                'detail': f'Bias đa khung — {self.storyline.summary()}',
            })

        # 1. Loại entry (CONFIRMED vs LIMIT/râu nến)
        if entry_type == 'CONFIRMED':
            items.append({
                'icon': '✅',
                'text': 'Entry <b>CONFIRMED</b> (market) — có nến Rejection',
                'detail': 'Râu từ chối đã đóng tại level → vào market.',
            })
        else:
            items.append({
                'icon': '🎣',
                'text': f'Entry <b>LIMIT</b> (râu nến) @ <b>{entry:.2f}</b>',
                'detail': 'Đặt limit nghỉ tại level, đón râu spike — KHÔNG chờ confirm.',
            })

        # 2. A/V Level
        if lv:
            l0 = lv[0]
            name = 'A-Level (Khang Cu)' if l0.level_type == 'A' else 'V-Level (Ho Tro)'
            tags = []
            if l0.is_miss:       tags.append('MISS')
            if l0.role_reversed: tags.append('FLIP')
            tag = (' [' + '+'.join(tags) + ']') if tags else ''
            items.append({
                'icon': '🔴' if action == 'SELL' else '🟢',
                'text': f'{name} {l0.state}{tag} @ <b>{l0.price:.2f}</b> ({tf})',
                'detail': 'Chua bi wick cham' if l0.state == 'FRESH' else 'Da cham — van hieu luc',
            })

        # 3. QM
        if qm:
            q = qm[0]
            items.append({
                'icon': '🧩',
                'text': f'Quasimodo {action} — vai phai @ <b>{q.entry:.2f}</b>',
                'detail': f'SL chuan MSNR tren apex @ {q.apex:.2f} (khong can fresh/unfresh).',
            })

        # 4. Trendline P3
        if p3:
            t0 = p3[0]
            dir_name = 'DOWN (Giam)' if t0.direction == 'DOWN' else 'UP (Tang)'
            p3p = round(t0.p3_price, 2) if t0.p3_price else entry
            items.append({
                'icon': '📐',
                'text': f'P3 Trendline {dir_name} ({tf})',
                'detail': f'Wick cham trendline @ {p3p:.2f}, than nen trong zone',
            })

        # 5. Roadblock / MISS / Gap (bonus)
        if rb_hit:
            items.append({'icon': '🚧',
                          'text': 'Tai ROADBLOCK (khung duoi storyline)',
                          'detail': 'Vung pullback ky vong truoc khi di tiep theo storyline.'})
        if gap:
            g0 = gap[0]
            gname = 'Gap Resistance' if g0.level_type == 'GAP_R' else 'Gap Support'
            items.append({'icon': '⚡',
                          'text': f'{gname} @ <b>{g0.price:.2f}</b> ({tf}) ✨bonus',
                          'detail': 'Vung mat can bang gia (imbalance/FVG).'})

        # 6. TP (co dinh $15)
        rr = round(FIXED_TP_USD / FIXED_SL_USD, 2)
        items.append({'icon': '🎯',
                      'text': f'TP co dinh +${FIXED_TP_USD:.0f} @ <b>{tp:.2f}</b> ({tf})',
                      'detail': f'SL ${FIXED_SL_USD:.0f} | RR {rr:.2f}:1 '
                                f'(crash → thao TP + trail ATR×{CRASH_ATR_MULT})'})

        signal['analysis_items'] = items
        signal['analysis_tf']    = tf
        return signal

    # ─────────────────────────────────────────────────────────────────────────
    @staticmethod
    def write_signal(signal):
        payload = signal if signal else {
            'action': 'NONE', 'status': 'NO_SETUP',
            'timestamp': datetime.utcnow().isoformat(),
        }
        payload['ts_epoch'] = int(time.time())
        os.makedirs(os.path.dirname(SIGNAL_FILE), exist_ok=True)
        with open(SIGNAL_FILE, 'w') as f:
            json.dump(payload, f, indent=2)
        log.info(f'Signal written: {payload["action"]} '
                 f'({payload.get("entry_type","-")}/{payload.get("order_type","-")})')

    @staticmethod
    def read_signal():
        if not os.path.exists(SIGNAL_FILE):
            return {'action': 'NONE'}
        with open(SIGNAL_FILE) as f:
            return json.load(f)
