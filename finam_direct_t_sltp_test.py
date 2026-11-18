#!/usr/bin/env python3
"""One-off LONG test of Finam SL/TP on T. Never imports or runs the scanner."""
import os
import sys
from datetime import datetime, timedelta, time as dt_time
from decimal import Decimal

import finam_executor as fe

TICKER = "T"
SYMBOL = "T@MISX"
CONFIRMATION = "BUY_T_ONCE"


def check_session():
    now = datetime.utcnow() + timedelta(hours=3)
    if now.weekday() >= 5 or not (dt_time(6, 50) <= now.time() <= dt_time(23, 50)):
        raise RuntimeError("Сейчас вне допустимого торгового окна MOEX.")


def main():
    if not fe.DRY_RUN and os.getenv("FINAM_DIRECT_TEST_CONFIRM", "") != CONFIRMATION:
        raise RuntimeError("Нет отдельного подтверждения BUY_T_ONCE.")
    fe.enforce_live_trading_gate(
        fe.DRY_RUN, os.getenv("FINAM_LIVE_TRADING_ENABLED", "false")
    )
    if not fe.FINAM_SECRET or not fe.ACCOUNT_ID:
        raise RuntimeError("Не заданы учётные данные Finam.")
    check_session()

    token = fe.get_jwt_token()
    account, _ = fe.get_account_info(token)
    if account.get("account_id") and str(account["account_id"]) != str(fe.ACCOUNT_ID):
        raise RuntimeError("Finam вернул другой счёт.")
    if fe.get_position_quantity(account, SYMBOL) != 0:
        raise RuntimeError("По T уже есть позиция. Тест остановлен.")
    if TICKER in fe.get_active_order_symbols(token):
        raise RuntimeError("По T уже есть активная заявка или SL/TP. Тест остановлен.")

    lot = fe.get_trade_parameters(token, TICKER, "LONG")
    quantity = fe.calculate_order_quantity(TICKER, 1, lot)
    if quantity != lot:
        raise RuntimeError("Не удалось подтвердить минимальный торговый лот.")

    print(f"Инструмент: {SYMBOL}; направление: LONG; минимальный лот: {lot} акций.")
    print("Защита: SL 3% ниже фактической средней цены; TP 5% выше.")
    if fe.DRY_RUN:
        print("DRY RUN: проверка завершена. Рыночная заявка НЕ отправлена.")
        return

    # Exactly one market-order POST. No retries are made by this script.
    result = fe.place_market_order(token, SYMBOL, quantity, "SIDE_BUY")
    order_id = result["order_id"]
    final_state = fe.wait_for_terminal_order(token, order_id)
    status = fe._normalized_order_status(final_state)
    executed = fe._decimal_value(final_state.get("executed_quantity"), "executed_quantity")
    if executed <= 0 or executed != executed.to_integral_value():
        raise fe.OrderProtectionError(
            f"Рыночная заявка завершилась без целого исполнения (status={status}, qty={executed})."
        )

    filled_qty, avg_price = fe.get_weighted_average_fill(
        token, order_id, result["submitted_at"], executed
    )
    filled_qty = int(filled_qty)
    fe.wait_for_position_quantity(token, SYMBOL, "LONG", filled_qty)

    sl_raw, tp_raw = fe.calculate_protective_prices(avg_price, "LONG")
    sl_price = fe.round_price_to_tick(token, TICKER, sl_raw, fe.ROUND_FLOOR)
    tp_price = fe.round_price_to_tick(token, TICKER, tp_raw, fe.ROUND_CEILING)

    if not fe.place_sltp_order(
        token, SYMBOL, filled_qty, "LONG", sl_price, tp_price
    ):
        raise fe.OrderProtectionError(
            "Finam отклонил SL/TP. Позиция может оставаться без защиты; нужна ручная проверка."
        )

    print("УСПЕХ: Finam подтвердил активную SL/TP заявку повторным чтением.")
    print(f"Исполнено: {filled_qty} акций; средняя цена: {avg_price}")
    print(f"SL: {sl_price}; TP: {tp_price}; SL/TP проверены у брокера.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ТЕСТ ОСТАНОВЛЕН: {type(exc).__name__}: {exc}", file=sys.stderr)
        if not fe.DRY_RUN:
            fe.send_telegram_message(
                "🚨 <b>Тест SL/TP по T остановлен</b>\n"
                + str(exc)[:2500]
                + "\nПроверь позицию и заявки T в Finam вручную."
            )
        raise
