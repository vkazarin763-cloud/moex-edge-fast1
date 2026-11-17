"""Read-only MOEX EDGE signal notifier. Never places orders or edits AI portfolio/weights."""
import json
import os
import html
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

import moex_edge_fast_33 as edge

TZ = ZoneInfo("Europe/Moscow")
STATE_FILE = Path("signal_bot_state.json")
LOG_FILE = Path("signal_bot_log.csv")
WEIGHTS_FILE = Path("ai_weights.json")
MIN_D1_BARS = 200
MIN_H1_BARS = 20
D1_LOOKBACK_DAYS = 420
H1_LOOKBACK_DAYS = 10
MIN_PRIORITY = edge.MIN_PRIORITY_THRESHOLD


def load_json(path, default):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def telegram_send(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID GitHub secret")
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message, "parse_mode": "HTML",
              "disable_web_page_preview": True},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API rejected message: {payload}")
    return payload


def clean_candles(df):
    if df.empty:
        return df
    df = df.copy()
    df["begin"] = pd.to_datetime(df["begin"], errors="coerce")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["begin", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset=["begin"], keep="last").sort_values("begin")
    valid = (
        (df["high"] >= df[["open", "close", "low"]].max(axis=1))
        & (df["low"] <= df[["open", "close", "high"]].min(axis=1))
        & (df[["open", "high", "low", "close"]] > 0).all(axis=1)
        & (df["volume"] >= 0)
    )
    return df.loc[valid].reset_index(drop=True)


def get_closed_d1(ticker, now):
    start = (now - timedelta(days=D1_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    df = clean_candles(edge.fetch_candles(ticker, 24, start, end))
    if df.empty:
        return df
    # Daily candle for the current Moscow date may still be forming: never use it.
    return df[df["begin"].dt.date < now.date()].reset_index(drop=True)


def get_closed_h1(ticker, now):
    start = (now - timedelta(days=H1_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    df = clean_candles(edge.fetch_candles(ticker, 60, start, end))
    if df.empty:
        return df
    # MOEX timestamps are naive exchange-local timestamps; require a fully elapsed hour.
    cutoff = now.replace(tzinfo=None)
    return df[df["begin"] + pd.Timedelta(hours=1) <= cutoff].reset_index(drop=True)


def select_signal(d1, weights):
    enriched = edge.calc_indicators(d1)
    candidates = edge.get_signals(enriched)
    candidates = [s for s in candidates if edge.STRATEGY_PRIORITY.get(s[2], 0) >= MIN_PRIORITY]
    if not candidates:
        return None
    # Preserve the scanner's minimum priority gate; AI weights break ties / rank candidates.
    candidates.sort(
        key=lambda s: (edge.STRATEGY_PRIORITY.get(s[2], 0), float(weights.get(s[2], 1))),
        reverse=True,
    )
    return candidates[0]


def format_signal(ticker, direction, strategy, d1_time, d1_close, h1_time,
                  h1_close, h1_ema, confirmed, ai_weight):
    status = "✅ H1 ПОДТВЕРЖДЁН" if confirmed else "⏳ H1 НЕ ПОДТВЕРЖДЁН"
    side = "🟢 LONG" if direction == 1 else "🔴 SHORT"
    h1_rule = "закрытие H1 выше EMA20" if direction == 1 else "закрытие H1 ниже EMA20"
    return (
        f"<b>MOEX EDGE — НОВЫЙ СИГНАЛ</b>\n"
        f"{side} <b>{html.escape(ticker)}</b>\n"
        f"Стратегия: <b>{html.escape(strategy)}</b>\n"
        f"Приоритет EDGE: {edge.STRATEGY_PRIORITY.get(strategy, 0)} | "
        f"Вес AI: {ai_weight:g}\n"
        f"D1 дата сигнала: {d1_time:%Y-%m-%d}\n"
        f"Цена закрытия D1: {d1_close:.2f}\n"
        f"H1 закрытие: {h1_close:.2f} ({h1_time:%Y-%m-%d %H:%M})\n"
        f"H1 EMA20: {h1_ema:.2f}\n"
        f"Проверка: {h1_rule}\n"
        f"<b>{status}</b>\n"
        f"<i>Информационный сигнал, не заявка. Цена не гарантирует исполнение. "
        f"Размер позиции и уровни выхода не рассчитываются.</i>"
    )


def append_log(record):
    row = pd.DataFrame([record])
    row.to_csv(LOG_FILE, mode="a", header=not LOG_FILE.exists(), index=False, encoding="utf-8")


def run():
    now = datetime.now(TZ).replace(tzinfo=None)
    weights = load_json(WEIGHTS_FILE, {})
    state = load_json(STATE_FILE, {"sent": {}})
    sent = state.setdefault("sent", {})
    sent_count = 0
    errors = []

    print(f"MOEX EDGE Signal Bot scan at {now:%Y-%m-%d %H:%M} MSK", flush=True)
    print(f"Universe: {len(edge.TICKERS)} tickers; read-only mode", flush=True)

    for ticker in edge.TICKERS:
        try:
            d1 = get_closed_d1(ticker, now)
            if len(d1) < MIN_D1_BARS:
                print(f"SKIP {ticker}: only {len(d1)} closed D1 candles", flush=True)
                continue
            selected = select_signal(d1, weights)
            if selected is None:
                continue

            d1_time, direction, strategy = selected
            h1 = get_closed_h1(ticker, now)
            if len(h1) < MIN_H1_BARS:
                print(f"SKIP {ticker}: insufficient closed H1 candles", flush=True)
                continue
            h1["ema20"] = h1["close"].ewm(span=20, adjust=False).mean()
            last = h1.iloc[-1]
            h1_close = float(last["close"])
            h1_ema = float(last["ema20"])
            confirmed = h1_close > h1_ema if direction == 1 else h1_close < h1_ema
            ai_weight = float(weights.get(strategy, 1))
            d1_close = float(d1.iloc[-1]["close"])
            key = f"{ticker}|{direction}|{strategy}|{pd.Timestamp(d1_time).date()}"
            status = "confirmed" if confirmed else "pending"
            previous = sent.get(key, {})
            # Send a fresh signal once, then only notify when H1 changes from pending to confirmed.
            should_send = not previous or (
                previous.get("status") != "confirmed" and confirmed
            )
            record = {
                "timestamp_msk": now.isoformat(timespec="minutes"),
                "ticker": ticker, "direction": "LONG" if direction == 1 else "SHORT",
                "strategy": strategy, "d1_signal_time": str(d1_time),
                "d1_close": d1_close, "h1_time": str(last["begin"]),
                "h1_close": h1_close, "h1_ema20": h1_ema,
                "h1_confirmed": confirmed, "ai_weight": ai_weight,
            }
            append_log(record)
            print(f"{ticker} {record['direction']} {strategy}: H1={status}", flush=True)
            if should_send:
                telegram_send(format_signal(
                    ticker, direction, strategy, pd.Timestamp(d1_time).to_pydatetime(),
                    d1_close, pd.Timestamp(last["begin"]).to_pydatetime(),
                    h1_close, h1_ema, confirmed, ai_weight,
                ))
                sent[key] = {"status": status, "last_h1": str(last["begin"])}
                sent_count += 1
        except Exception as exc:
            errors.append(f"{ticker}: {type(exc).__name__}: {exc}")
            print(f"ERROR {errors[-1]}", flush=True)

    state["updated_at_msk"] = now.isoformat(timespec="minutes")
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print(f"Finished. Telegram notifications: {sent_count}; errors: {len(errors)}", flush=True)
    if errors:
        raise RuntimeError("Some tickers failed: " + " | ".join(errors[:10]))


if __name__ == "__main__":
    run()
