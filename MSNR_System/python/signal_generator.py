import json, os, logging
from datetime import datetime
from config import (SIGNAL_FILE, RISK_PCT, FIXED_SL_USD,
                    MIN_RR, TRAIL_TRIGGER, TRAIL_LOCK_USD, MAX_LOT,
                    PRIMARY_TF)

log = logging.getLogger('MSNR.Signal')


def calc_lot(balance):
    risk_usd = balance * RISK_PCT / 100
    lot = risk_usd / (FIXED_SL_USD * 100)
    return round(min(max(lot, 0.01), MAX_LOT), 2)


def _collect_nearby_levels(detector, center_price, n=6):
    fresh = detector.get_fresh_levels()
    sorted_levels = sorted(fresh, key=lambda l: abs(l.price - center_price))
    result = []
    for lv in sorted_levels[:n]:
        t = lv.level_type[0] if lv.level_type[0] in ('A','V') else 'G'
        result.append({'t': t, 'p': round(lv.price, 2),
                       'tf': PRIMARY_TF, 'fresh': lv.state == 'FRESH'})
    return result


def _flat_levels(nearby):
    """Convert list to flat keys lv0_t, lv0_p, lv1_t, ... for EA parsing"""
    d = {'lv_cnt': len(nearby)}
    for i, lv in enumerate(nearby):
        d[f'lv{i}_t'] = lv['t']
        d[f'lv{i}_p'] = lv['p']
    return d


def _build_analysis(action, signal, p3_list, fresh_list, tp, entry, tf):
    items = []
    if fresh_list:
        lv = fresh_list[0]
        ltype_name = 'A-Level (Khang Cu)' if lv.level_type in ('A','GAP_R') else 'V-Level (Ho Tro)'
        state = 'FRESH' if lv.state == 'FRESH' else 'UNFRESH'
        items.append({
            'icon': '🔴' if action == 'SELL' else '🟢',
            'text': f'{ltype_name} {state} @ <b>{lv.price:.2f}</b> ({tf})',
            'detail': 'Chua bi wick cham — vung moi chua duoc kiem tra'
                      if state == 'FRESH' else 'Da bi cham 1 lan — van hieu luc',
        })
    if p3_list:
        tl = p3_list[0]
        dir_name = 'DOWN (Giam)' if tl.direction == 'DOWN' else 'UP (Tang)'
        p3_price = round(tl.p3_price, 2) if tl.p3_price else entry
        items.append({
            'icon': '📐',
            'text': f'P3 Trendline {dir_name} ({tf})',
            'detail': f'Wick cham trendline tai {p3_price:.2f}, than nen nam trong zone',
        })
        signal['tl_dir'] = tl.direction
        signal['tl_p3']  = p3_price

    rr = round(abs(tp - entry) / FIXED_SL_USD, 1)
    tp_label = 'V-Level (Ho Tro)' if action == 'SELL' else 'A-Level (Khang Cu)'
    items.append({
        'icon': '🎯',
        'text': f'TP tai {tp_label} @ <b>{tp:.2f}</b> ({tf})',
        'detail': f'RR {rr:.1f}:1',
    })
    signal['analysis_items'] = items
    signal['analysis_tf']    = tf
    return signal


class SignalGenerator:
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
        if sig: return sig
        return self._check_buy(active_p3, fresh)

    def _tp_sell(self):
        min_tp = self.price - FIXED_SL_USD * MIN_RR
        v_levels = sorted(
            [l for l in self.detector.get_fresh_levels()
             if l.level_type in ('V','GAP_S') and l.price < min_tp],
            key=lambda l: l.price, reverse=True)
        return round(v_levels[0].price, 2) if v_levels else round(min_tp, 2)

    def _tp_buy(self):
        min_tp = self.price + FIXED_SL_USD * MIN_RR
        a_levels = sorted(
            [l for l in self.detector.get_fresh_levels()
             if l.level_type in ('A','GAP_R') and l.price > min_tp],
            key=lambda l: l.price)
        return round(a_levels[0].price, 2) if a_levels else round(min_tp, 2)

    def _check_sell(self, active_p3, fresh):
        tol = 1.5
        p3_sell = [t for t in active_p3
                   if t.direction == 'DOWN' and t.p3_price
                   and abs(t.p3_price - self.price) <= tol]
        fresh_r = [l for l in fresh
                   if l.level_type in ('A','GAP_R')
                   and abs(l.price - self.price) <= tol]
        if not p3_sell and not fresh_r: return None

        sl = round(self.price + FIXED_SL_USD, 2)
        tp = self._tp_sell()
        rr = round((self.price - tp) / FIXED_SL_USD, 1)
        nearby = _collect_nearby_levels(self.detector, self.price)

        signal = {
            'action':'SELL','entry':round(self.price,2),'sl':sl,'tp':tp,
            'lot':self.lot,'sl_usd':FIXED_SL_USD,
            'trail_trigger':TRAIL_TRIGGER,'trail_lock_usd':TRAIL_LOCK_USD,
            'rr':rr,'confluence':len(p3_sell)+len(fresh_r),
            'p3_trendline':bool(p3_sell),'fresh_level':bool(fresh_r),
            'nearby_levels':nearby,'timestamp':datetime.utcnow().isoformat(),
            'status':'PENDING',
        }
        signal.update(_flat_levels(nearby))
        _build_analysis('SELL', signal, p3_sell, fresh_r, tp, self.price, PRIMARY_TF)
        return signal

    def _check_buy(self, active_p3, fresh):
        tol = 1.5
        p3_buy  = [t for t in active_p3
                   if t.direction == 'UP' and t.p3_price
                   and abs(t.p3_price - self.price) <= tol]
        fresh_s = [l for l in fresh
                   if l.level_type in ('V','GAP_S')
                   and abs(l.price - self.price) <= tol]
        if not p3_buy and not fresh_s: return None

        sl = round(self.price - FIXED_SL_USD, 2)
        tp = self._tp_buy()
        rr = round((tp - self.price) / FIXED_SL_USD, 1)
        nearby = _collect_nearby_levels(self.detector, self.price)

        signal = {
            'action':'BUY','entry':round(self.price,2),'sl':sl,'tp':tp,
            'lot':self.lot,'sl_usd':FIXED_SL_USD,
            'trail_trigger':TRAIL_TRIGGER,'trail_lock_usd':TRAIL_LOCK_USD,
            'rr':rr,'confluence':len(p3_buy)+len(fresh_s),
            'p3_trendline':bool(p3_buy),'fresh_level':bool(fresh_s),
            'nearby_levels':nearby,'timestamp':datetime.utcnow().isoformat(),
            'status':'PENDING',
        }
        signal.update(_flat_levels(nearby))
        _build_analysis('BUY', signal, p3_buy, fresh_s, tp, self.price, PRIMARY_TF)
        return signal

    def write_signal(self, signal):
        payload = signal if signal else {
            'action':'NONE','status':'NO_SETUP',
            'timestamp':datetime.utcnow().isoformat(),
        }
        os.makedirs(os.path.dirname(SIGNAL_FILE), exist_ok=True)
        with open(SIGNAL_FILE, 'w') as f:
            json.dump(payload, f, indent=2)
        log.info(f'Signal written: {payload["action"]}')

    @staticmethod
    def read_signal():
        if not os.path.exists(SIGNAL_FILE): return {'action':'NONE'}
        with open(SIGNAL_FILE) as f: return json.load(f)
