import time, logging, sys, os
import pandas as pd
import MetaTrader5 as mt5

sys.path.insert(0, os.path.dirname(__file__))
from config import (SYMBOL, PRIMARY_TF, LOOKBACK_BARS, LOG_FILE,
                    MT5_PATH, MT5_LOGIN, MT5_PASSWORD, MT5_SERVER,
                    FIXED_SL_USD, TRAIL_TRIGGER, TRAIL_LOCK_USD, RISK_PCT)
from msnr_detector import MSNRDetector
from trendline import TrendlineEngine
from signal_generator import SignalGenerator, calc_lot

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8', mode='a'),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger('MSNR.Main')

TF_MAP = {
    'M1' : mt5.TIMEFRAME_M1,  'M5' : mt5.TIMEFRAME_M5,
    'M15': mt5.TIMEFRAME_M15, 'M30': mt5.TIMEFRAME_M30,
    'H1' : mt5.TIMEFRAME_H1,  'H4' : mt5.TIMEFRAME_H4,
    'D1' : mt5.TIMEFRAME_D1,
}

def connect_mt5():
    for attempt, kwargs in enumerate([
        {},
        {'path': MT5_PATH},
        {'path': MT5_PATH, 'login': MT5_LOGIN,
         'password': MT5_PASSWORD, 'server': MT5_SERVER},
    ], 1):
        if mt5.initialize(**kwargs):
            info = mt5.account_info()
            if info:
                log.info(f'MT5 OK (attempt {attempt}) | Account:{info.login} '
                         f'Balance:{info.balance}')
                return True
            mt5.shutdown()
    log.error(f'MT5 init failed: {mt5.last_error()}')
    return False

def get_ohlcv(symbol, tf, n):
    rates = mt5.copy_rates_from_pos(symbol, TF_MAP[tf], 0, n)
    if rates is None or len(rates) == 0:
        log.warning(f'No data {symbol} {tf}')
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

def run_cycle():
    df = get_ohlcv(SYMBOL, PRIMARY_TF, LOOKBACK_BARS)
    if df.empty:
        return

    tick = mt5.symbol_info_tick(SYMBOL)
    if not tick:
        mt5.symbol_select(SYMBOL, True)
        return

    price   = tick.bid
    info    = mt5.account_info()
    balance = info.balance if info else 10000.0
    lot     = calc_lot(balance)

    log.info(
        f'Cycle | {SYMBOL} | Price:{price:.2f} | Balance:{balance:.2f} | '
        f'Lot:{lot} | SL:${FIXED_SL_USD} | Trail:+${TRAIL_TRIGGER}->${TRAIL_LOCK_USD}'
    )

    detector   = MSNRDetector(df)
    levels     = detector.detect_all()
    fresh      = detector.get_fresh_levels()
    log.info(f'Levels:{len(levels)} | Fresh:{len(fresh)}')

    tl_engine  = TrendlineEngine(df, levels)
    trendlines = tl_engine.detect()
    p3s        = tl_engine.get_active_p3_signals(trendlines)
    log.info(f'Trendlines:{len(trendlines)} | P3:{len(p3s)}')

    sg     = SignalGenerator(detector, tl_engine, price, balance)
    signal = sg.generate(trendlines)

    if signal:
        log.info(
            f'SIGNAL -> {signal["action"]} '
            f'Entry:{signal["entry"]} SL:{signal["sl"]} TP:{signal["tp"]} '
            f'Lot:{signal["lot"]} RR:{signal["rr"]}:1 | '
            f'Trail: +${signal["trail_trigger"]} -> SL +${signal["trail_lock_usd"]}'
        )
    else:
        log.info('No setup this cycle')

    sg.write_signal(signal)

def main():
    log.info('=' * 55)
    log.info('MSNR v2.1 | SL=$18 | Trail: +$23 -> lock $18 (1R)')
    log.info('=' * 55)

    retries = 0
    while not connect_mt5():
        retries += 1
        if retries > 5:
            log.critical('Cannot connect MT5 — aborting')
            sys.exit(1)
        log.warning(f'Retry {retries}/5 in 30s...')
        time.sleep(30)

    mt5.symbol_select(SYMBOL, True)
    log.info(f'{SYMBOL} added to MarketWatch')

    try:
        while True:
            try:
                run_cycle()
            except Exception as e:
                log.exception(f'Cycle error: {e}')
            time.sleep(60)
    except KeyboardInterrupt:
        log.info('Stopped by user.')
    finally:
        mt5.shutdown()

if __name__ == '__main__':
    main()
