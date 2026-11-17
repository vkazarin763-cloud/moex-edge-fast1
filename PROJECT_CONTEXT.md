# MOEX EDGE — контекст проекта

Обновлено: 2026-11-16

## 1. Что это
- **Боевой контур (акции):** `moex_edge_fast_33.py` (MOEX EDGE FAST 4.0 Sniper Mode) 
  → `finam_executor.py` → **реальные заявки** через Finam. Это задумано, не отключать.
- **Виртуальный контур:** `ai_agent.py` (виртуальные сделки) + `ai_trainer.py` (веса стратегий). 
  Состояние: `ai_portfolio.json`, `ai_weights.json`. Реальных заявок не шлют.
- **Фьючерсы:** `futures_scanner.py` → `futures_executor.py` → реальные BUY по LONG-сигналам. 
  SHORT-сигналы пропускаются исполнителем.
- **Бэктесты:** ручные workflow (`backtest-*.yml`).

## 2. Текущее состояние (на 2026-11-16)
- **Планировщик:** Работает через внешний сервис `cron-job.org` (каждый час). Родной `schedule` в GitHub оставлен как резервный.
- **AI Agent:** Бот исправлен (защита от дублей + корректное время входа). Кэш: ~133 220 ₽. 6 открытых позиций. 
  Статистика: 6 закрытых сделок (0% Win Rate, -2205 ₽ — это хвост старого бага с ALRS, когда стопы срабатывали мгновенно). Новые сделки будут чистыми.
- **AI Trainer:** Прогон 16.11 показал топ-веса у Donchian20, ATR, Donchian55. 
- **Сканер акций:** Работает. Telegram-уведомления подтверждены.

## 3. Что сделано (последние решения)
- 2026-11-15: Аудит репозитория без изменений кода.
- 2026-11-16: Прогон ai_trainer, веса обновлены.
- 2026-11-16: Подключен внешний планировщик `cron-job.org` через API. Решена проблема пропусков запусков.
- 2026-11-16: Заведена внешняя память проекта (эти файлы).

## 4. Что в работе / следующие шаги
- Собираем статистику. Правила виртуального трейдера не менять до конца месячного окна.
- Наблюдать стабильность весов EMA20/50 и Morning_Star от прогона к прогону (риск шума на малых выборках).
- Сравнить фактические результаты реальных сделок с методикой trainer.
- Проверить завтра стабильность почасовых запусков от cron-job.org.
- **Архитектурное обновление (запланировано):** Переход с фиксированного TP 5% на `PARTIAL` (50% на +3%, остаток по ATR-трейлингу). Внедрение трейлинг-стопа на базе ATR (2.0). Отказ от фильтра Multi-входа.
- **Архитектурное обновление (ЗАПЛАНИРОВАНО, доказано бэктестом):**
  - Внедрить фильтр EMA200 для входа (запрет лонгов ниже EMA200, шортов выше).
  - Изменить логику выхода на `Partial_5.0`: 50% фиксируем при достижении +5%, переводим стоп в БУ, а остаток ведем по трейлинг-стопу 2.0 ATR.

## 5. Известные проблемы (не менять без ## 5. Известные проблемы (не менять без согласования)
- **Порог приоритета 7** в сканере: реально стреляют только Keltner, ATR, Donchian55, Donchian20.
- **Расхождение методик выхода:** trainer показывает PF 20 у ATR, что несовместимо с TP 5% / SL 3% в `finam_executor.py`.
- **Нет проверки закрытости D1/H1** в боевом сканере (требует аудита кода).
- **`futures-scan.yml` сломан** (Python-код вместо YAML). На боевой контур не влияет.
- ~~**AI Agent: баг с дублями**~~ (ИСПРАВЛЕНО 16.11.2026).

## 6. Правила безопасности
- Реальное исполнение в `moex-edge-fast.yml` и `futures-trade.yml` — задумано. Не отключать без прямого согласия.
- Секреты (`FINAM_API_SECRET`, `FINAM_ACCOUNT_ID`, `TELEGRAM_*`) не присылать в чат и не коммитить.
- Репозиторий публичный — проверять, что секреты не попали в код/логи.
- **GitHub Personal Access Token (PAT) для cron-job.org истекает в феврале 2027.** 
  За 2 недели до этого создать новый и обновить в cron-job.org, иначе запуски прекратятся.

## 7. AI Virtual Agent — исправление 2026-11-17
- Исправлено непосредственно в `main`: `get_kelly_pct()` находилась внутри `sigs()` после `return out`, поэтому глобального имени функции не существовало. При появлении подходящего сигнала `main()` доходил до вызова и завершался `NameError: name 'get_kelly_pct' is not defined`.
- Функция вынесена на уровень модуля; формула, пороги и размер доли не менялись.
- Добавлены `tests/test_ai_agent.py` и workflow `.github/workflows/ai-virtual-agent-tests.yml`: компиляция `ai_agent.py`/`ai_trainer.py` и три unit-теста Kelly.
- Состояние `ai_portfolio.json`, `ai_weights.json`, алгоритм `ai_trainer.py`, расписание AI Agent и торговые правила не менялись.
- Исправление опубликовано в `main`. Проверка CI ожидается; реальный ручной запуск агента не выполнялся в рамках исправления.

## 8. Finam Executor Telegram notifications — 2026-11-17
- В отдельной feature-ветке подготовлено подключение `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID` к шагу Finam Executor в обоих workflow: почасовом `moex-edge-fast.yml` и ручном `finam-executor.yml`.
- Изменение ограничено передачей GitHub Actions secrets в окружение executor; торговая логика, `FINAM_DRY_RUN`, сканер, расписание и параметры ордеров не менялись.
- Перед включением требуется проверить, что GitHub Actions secrets заведены под точными именами `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID`. Значения секретов не читаются и не выводятся.
- Подключение в `main` активируется только после проверки PR. При `FINAM_DRY_RUN=true` уведомления о фактическом исполнении не появятся, поскольку реальные заявки не отправляются.

## 9. Finam Executor hardening — PR in progress (2026-11-17)
- В отдельной ветке `fix/finam-executor-hardening-20261117` подготовлена защита отправки и сверки исполнения: `client_order_id`, запрет слепого повтора после неоднозначного POST, ожидание конечного статуса, отмена/сверка остатка, расчёт фактического VWAP по сделкам и SL/TP только на подтверждённое исполненное количество.
- В оба workflow добавлена передача `FINAM_DRY_RUN` из Actions Variable `vars.FINAM_DRY_RUN` с безопасным значением по умолчанию `true`. Некорректное значение теперь останавливает программу, а не включает реальную торговлю.
- Добавлены изолированные mock unit-тесты и workflow проверки. Проверки не используют Finam API и не отправляют брокерские заявки.
- Для намеренного боевого режима владелец репозитория должен самостоятельно задать Actions Variable `FINAM_DRY_RUN=false`; пока переменная отсутствует, режим остаётся DRY_RUN. Значения API-секретов не читаются и не меняются.
- PR Draft; main не изменён. Не запускать реальные заявки до проверки CI, ручной сверки Finam API схем и проверки наличия/корректности секретов.

## 10. Передача проекта другой ИИ (2026-11-17)
- Создан `HANDOFF_FOR_NEXT_AI.md` в ветке `fix/finam-executor-hardening-20261117`; документ содержит карту репозитория, состояние PR, проверенные CI, границы безопасности и следующие шаги.
- В документе зафиксировано: PR #5 Draft/open, не объединён; последний CI успешен, 10/10 mock unit-тестов; реальные заявки не отправлялись; `FINAM_DRY_RUN` не переключался в false.
- Зафиксировано требование не запускать реальную торговлю до аудита Finam API, настроек Actions и защитных сценариев.

## 11. Повторный аудит Finam Executor (2026-11-17)
- В официальных контрактах Finam подтверждены поля `client_order_id` (до 20 символов), `AccountTrade.order_id/price/size`, а также методы GetOrders/GetOrder/CancelOrder/Trades/PlaceSLTPOrder.
- Найдено и исправлено: HTTP 200 от PlaceSLTPOrder ранее считался доказательством защиты без разбора ответа. Теперь проверяются order_id, объект sltp_order, отсутствие статуса отказа и совпадение подтверждённых количеств/цен SL и TP.
- Найдено и исправлено: цены SL/TP округлялись фиксированно до 2 знаков. Теперь используется GetAsset (decimals/min_step/price_step) с округлением в безопасную сторону для LONG/SHORT; отсутствие шага цены блокирует заявку.
- Добавлены тесты на ответы SL/TP и фиксированный/ценозависимый шаг цены.
- Последний коммит кода/тестов: c30cdd9ae5c1b99f6a0bd5130c1cd7d9f9aa9555. CI для этого коммита ещё не подтверждён; предыдущий run 44140543355 успешен на более раннем SHA 6e30a80733f8bfa463aac62974946ab1ed4a3cda.
- PR #5 остаётся Draft/open; main не изменён. FINAM_DRY_RUN не переключался, секреты не читались/не менялись, брокерские запросы и реальные заявки не отправлялись.

- Повторный CI для изменений в executor, тестах и журналах завершился успешно: run 44141464912, компиляция прошла, 14/14 тестов — OK (commit a19e63308cef5dec7345abcc87abd73e87380663). Последующее обновление handoff фиксирует этот результат; CI должен быть повторно проверен на новом HEAD после финальной записи.

- В safety CI добавлена проверка только наличия runtime secrets (значения не печатаются). Run 44141866777 подтвердил наличие FINAM_API_SECRET, FINAM_ACCOUNT_ID, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID; эффективный FINAM_DRY_RUN=safe.
- Перед заявкой добавлена проверка разрешения направления по Finam GetAssetParams: LONG требует AVAILABLE; SHORT — AVAILABLE или AVAILABLE_STRATEGY. HTB/запрещённые статусы блокируются.
- Актуальный CI run 44141866777: compile success, 16/16 unit tests OK. Проверка конфигурации не обращалась к брокеру и не читала счёт.

## 12. Read-only Finam integration and position cap (2026-11-17)
- Выполнен read-only аудит через реальные Finam API credentials: авторизация и GET счёта успешны; 44/44 инструментов имеют корректные параметры лота и шага цены; последняя проверка подтвердила LONG 44/44 и SHORT 44/44, 0 неторгуемых инструментов, 0 ошибок (run 44143080070). Ранее один проход показал SHORT 43/44; разрешения проверяются непосредственно перед каждой заявкой.
- Аудит использовал только POST /v1/sessions и GET endpoints аккаунта/инструментов; order endpoints не вызывались, реальные заявки не отправлялись.
- В executor добавлен жёсткий MAX_OPEN_POSITIONS=10, учитывающий symbols из позиций Finam, включая теоретическую экспозицию активных заявок. При 10 позициях новые инструменты пропускаются.
- TEST_MODE_MIN_VOLUME=True сохранён: eventual live заявки ограничены одним минимальным лотом инструмента.
- CI run 44143462329: compile success, 19/19 unit tests OK. Четыре secrets присутствуют; FINAM_DRY_RUN=safe.
- PR #5 остаётся Draft/open, main не изменён, боевой режим не включён.

## 13. Финальная проверка исполнения/защиты (2026-11-17)
- Trade history после terminal order state теперь сверяется повторно до 10 раз, пока количество сделок не совпадёт с executed_quantity; несовпадение или превышение блокирует SL/TP и вызывает critical alert.
- После POST SL/TP executor выполняет GET GetOrder read-back: проверяет активный статус, отсутствие triggered_order_id, совпадение order_id, symbol, exit side, SL/TP quantity и prices. Отказ/неизвестный статус/несовпадение останавливает следующие сигналы.
- Баланс, список открытых инструментов и сектора больше не выводятся в workflow logs; логируются только количества.
- Latest CI run 44144452367: compile success, 24/24 unit tests OK; secrets present; FINAM_DRY_RUN=safe.
- Read-only audit 44143080070: 44/44 лот/шаг цены, 44/44 LONG и 44/44 SHORT; order endpoints не вызывались.
- Реальные заявки и SL/TP не отправлялись. Фактический жизненный цикл SL/TP на реальном/демо ордере остаётся не проверен; PR #5 Draft/open, main не изменён.

- Дополнительно исправлен лимит позиций: теперь перед запуском объединяются символы реальных позиций и активных заявок из GET /orders; активные и неизвестные статусы резервируют слот; при ошибке чтения списка заявок новые сделки не отправляются. MAX_OPEN_POSITIONS=10.
- CI для commit 011d9a98a4f25b12bef5e179ac88d01471d4f2e8: run 44156645285, compile + 27/27 unit tests passed. Секреты присутствуют, FINAM_DRY_RUN=safe.
- Finam docs подтвердили GetOrders/GetOrder и длину client_order_id до 20 символов; не документируют idempotency guarantee, поэтому код только ищет заявку по id и не повторяет POST.
- Live всё ещё не включён; нужны sandbox integration tests по partial fills, cancel race, SL/TP lifecycle и orphan exposure.

 
## Finam Executor — follow-up audit (2026-11-17)
- PR #5 branch head: `bf7ed4f110f1a25551cef1d471ef5ade08d8ee0a`; latest safety CI run `44157773263` completed successfully.
- Latest CI: Python compile passed; 30/30 unit tests passed; required Finam/Telegram secrets present (values masked); effective `FINAM_DRY_RUN=true`.
- Added SL/TP client_order_id and read-only reconciliation on timeout/5xx/408; no blind retry. SL/TP volume units explicitly set to `SLTP_QTY_MEASURE_VALUE`.
- Active order without a resolvable symbol now fails closed. Unexpected exceptions after market-order submission are escalated through the critical alert path.
- Official Finam docs confirm `SLTP_QTY_MEASURE_VALUE` means shares, `SLTP_QTY_MEASURE_PERCENT` means a percentage of position; GetAsset price-dependent tick selection uses `step` below threshold and `step_from_threshold` at/above threshold.
- Remaining blockers: full demo-account order lifecycle test (market order, partial/late fill, cancel race, trades reconciliation, SL/TP create/read-back); reliable handling of unprotected/orphan exposure if SL/TP cannot be confirmed; durable signal deduplication (current executor can re-enter after a position closes if the same signal remains in `moex_signals.csv`); final live workflow review.
- No live orders were sent; PR #5 is Draft/open/unmerged; main unchanged; `FINAM_DRY_RUN` remains true.

 
## PR head after journal update
- Journal-only follow-up commits advanced PR #5 to `531c9fe0e151be95e40a464a780f8653d04f421c`.
- The executor code and tests validated by run `44157773263` are unchanged from code commit `bf7ed4f110f1a25551cef1d471ef5ade08d8ee0a`; the later commits only update project journals and PR documentation.

## 2026-11-17 — persistent signal deduplication and workflow wiring
- Reviewed the current Finam Executor branch. Durable signal fingerprint/state functions were present in the executor, but the scheduled scanner+executor workflow did not pass the GitHub token/repository/ref and did not serialize against manual executor runs. Without those settings, live-mode signal-state persistence would fail closed before order submission.
- Updated `.github/workflows/moex-edge-fast.yml`: grant only `contents: write`, serialize the full scan+execute workflow with concurrency group `finam-executor-account`, and pass `github.token`, repository and ref to the executor.
- Updated `.github/workflows/finam-executor.yml` to use the Actions runtime token (`github.token`) for the durable journal; it already had the same concurrency group and contents-write permission.
- Executor now records terminal zero-fill outcomes as `NO_FILL_TERMINAL` with order id/status/zero filled quantity. The signal remains consumed to prevent a stale active CSV row from triggering a duplicate order.
- Reset `signal_id` for each CSV row so an earlier iteration's identifier cannot leak into a later exception path.
- Changes are on Draft PR #5 branch only. CI for the newest commits has not yet been observed. No executor workflow was dispatched and no broker order was sent. Keep `FINAM_DRY_RUN=true`.
