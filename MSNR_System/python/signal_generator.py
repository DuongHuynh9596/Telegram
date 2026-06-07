import json, os, logging
from datetime import datetime
from config import (SIGNAL_FILE, RISK_PCT, FIXED_SL_USD,
                    MIN_RR, TRAIL_TRIGGER, TRAIL_LOCK_USD, MAX_LOT)

log = logging.getLogger('MSNR.Signal')


def calc_lot(balance):
    """lot = risk_usd / (sl_usd * 100)  | XAUUSD: 1 lot = $100/dollar"""
    risk_usd = balance * RISK_PCT / 100
    lot = risk_usd / (FIXED_SL_USD * 100)
    return round(min(max(lot, 0.01), MAX_LOT), 2)


class SignalGenerator:
    """
    SL   : entry +/- $18 (fixed, price movement)
    TP   : next fresh MSNR level, minimum 1:1 ($18)
    Lot  : < 1% account risk
    Trail: EA xu ly — khi lai $23 doi SL ve entry +/- $18 (lock 1R)
    """

    def __init__(self, detector, tl_engine, current_price, balance):
        self.detector  = detector
        self.tl_engine = tl_engine
        self.price     = current_price
        self.balance   = balance
        self.lot       = calc_lot(balance)

    def generate(self, trendlines):
        active_p3 = self.tl_engine.get_active_p3_signals(trendlines)
        fresh     = self.detector.get_fresh_levels()

        sig = self._check_sell(active_p3, fresh)
        if sig:
            return sig
        return self._check_buy(active_p3, fresh)

    # ── TP helpers ─────────────────────────────────────────────────

    def _tp_sell(self):
        """Next fresh V/GAP_S level below entry, min 1:1"""
        min_tp = self.price - FIXED_SL_USD * MIN_RR
        v_levels = sorted(
            [l for l in self.detector.get_fresh_levels()
             if l.level_type in ('V', 'GAP_S') and l.price < min_tp],
            key=lambda l: l.price, reverse=True   # closest below
        )
        if v_levels:
            tp = v_levels[0].price
            rr = (self.price - tp) / FIXED_SL_USD
            log.info(f'TP(SELL) V-level {tp:.2f} | RR {rr:.1f}:1')
            return round(tp, 2)
        return round(min_tp, 2)   # fallback 1:1

    def _tp_buy(self):
        """Next fresh A/GAP_R level above entry, min 1:1"""
        min_tp = self.price + FIXED_SL_USD * MIN_RR
        a_levels = sorted(
            [l for l in self.detector.get_fresh_levels()
             if l.level_type in ('A', 'GAP_R') and l.price > min_tp],
            key=lambda l: l.price    # closest above
        )
        if a_levels:
            tp = a_levels[0].price
            rr = (tp - self.price) / FIXED_SL_USD
            log.info(f'TP(BUY) A-level {tp:.2f} | RR {rr:.1f}:1')
            return round(tp, 2)
        return round(min_tp, 2)

    # ── Signal builders ────────────────────────────────────────────

    def _check_sell(self, active_p3, fresh):
        tol = 1.5
        p3_sell = [t for t in active_p3
                   if t.direction == 'DOWN' and t.p3_price
                   and abs(t.p3_price - self.price) <= tol]
        fresh_r = [l for l in fresh
                   if l.level_type in ('A', 'GAP_R')
                   and abs(l.price - self.price) <= tol]
        if not p3_sell and not fresh_r:
            return None

        sl = round(self.price + FIXED_SL_USD, 2)   # above entry
        tp = self._tp_sell()
        rr = round((self.price - tp) / FIXED_SL_USD, 1)

        return {
            'action'          : 'SELL',
            'entry'           : round(self.price, 2),
            'sl'              : sl,
            'tp'              : tp,
            'lot'             : self.lot,
            'sl_usd'          : FIXED_SL_USD,
            'trail_trigger'   : TRAIL_TRIGGER,   # $23 -> activate trail
            'trail_lock_usd'  : TRAIL_LOCK_USD,  # new SL = entry - $18
            'rr'              : rr,
            'confluence'      : len(p3_sell) + len(fresh_r),
            'p3_trendline'    : bool(p3_sell),
            'fresh_level'     : bool(fresh_r),
            'timestamp'       : datetime.utcnow().isoformat(),
            'status'          : 'PENDING',
        }

    def _check_buy(self, active_p3, fresh):
        tol = 1.5
        p3_buy  = [t for t in active_p3
                   if t.direction == 'UP' and t.p3_price
                   and abs(t.p3_price - self.price) <= tol]
        fresh_s = [l for l in fresh
                   if l.level_type in ('V', 'GAP_S')
                   and abs(l.price - self.price) <= tol]
        if not p3_buy and not fresh_s:
            return None

        sl = round(self.price - FIXED_SL_USD, 2)   # below entry
        tp = self._tp_buy()
        rr = round((tp - self.price) / FIXED_SL_USD, 1)

        return {
            'action'          : 'BUY',
            'entry'           : round(self.price, 2),
            'sl'              : sl,
            'tp'              : tp,
            'lot'             : self.lot,
            'sl_usd'          : FIXED_SL_USD,
            'trail_trigger'   : TRAIL_TRIGGER,
            'trail_lock_usd'  : TRAIL_LOCK_USD,  # new SL = entry + $18
            'rr'              : rr,
            'confluence'      : len(p3_buy) + len(fresh_s),
            'p3_trendline'    : bool(p3_buy),
            'fresh_level'     : bool(fresh_s),
            'timestamp'       : datetime.utcnow().isoformat(),
            'status'          : 'PENDING',
        }

    # ── I/O ────────────────────────────────────────────────────────

    def write_signal(self, signal):
        payload = signal if signal else {
            'action'   : 'NONE',
            'status'   : 'NO_SETUP',
            'timestamp': datetime.utcnow().isoformat(),
        }
        os.makedirs(os.path.dirname(SIGNAL_FILE), exist_ok=True)
        with open(SIGNAL_FILE, 'w') as f:
            json.dump(payload, f, indent=2)
        log.info(f'Signal written: {payload["action"]}')

    @staticmethod
    def read_signal():
        if not os.path.exists(SIGNAL_FILE):
            return {'action': 'NONE'}
        with open(SIGNAL_FILE) as f:
            return json.load(f)
