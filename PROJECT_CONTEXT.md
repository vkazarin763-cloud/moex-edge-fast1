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

## 2026-11-17 — verified signal-journal CI
- Run `44160419914` succeeded on PR merge commit `78f3a81` (branch code/test commit `682493b470758e26e4eb63355770d7633dfe0be0`): compile passed, 37/37 unit tests passed, including mocked GitHub Contents API journal read/write tests.
- All four required Actions secrets were reported present without exposing values; effective `FINAM_DRY_RUN=true`.
- Subsequent branch commits only changed project journals/handoff/PR description; tested executor code and test file were unchanged.
- PR #5 remains Draft/open/unmerged. No executor workflow was dispatched and no real broker order was sent.
- Live blockers remain: no demo account/full order lifecycle integration test, no safe automatic recovery from unprotected exposure, and actual Actions-token journal write still needs a non-trading workflow verification.

## 2026-11-17 — explicit branch variable for GitHub signal journal
- Real GitHub Actions integration test exposed that `GITHUB_REF_NAME` is a reserved runner variable and cannot be overridden from workflow `env`. On pull_request runs it resolves to `<number>/merge`, which caused GitHub Contents API 404 when saving the durable journal.
- Executor now prefers `FINAM_STATE_BRANCH` and falls back to the built-in `GITHUB_REF_NAME` only when the explicit variable is absent.
- Both executor workflows pass `FINAM_STATE_BRANCH: ${{ github.ref_name }}` for their schedule/manual execution context.
- A real, isolated integration run `44162894813` passed using the Actions token with Contents:write. It read and wrote a test-only signal state on branch `test/finam-journal-validation`; no Finam endpoint or broker order was used.
- The production code/workflow fix is in a separate PR branch pending its own safety CI. Keep `FINAM_DRY_RUN=true`.

## 2026-11-17 — final verified state after PR #8
- PR #5 Finam Executor hardening merged to main (merge commit `2e9379f7658958916c683bb507c9c8fe8ecc06f2`). It includes durable signal deduplication, reservation before order submission, fail-closed journal behavior, terminal zero-fill state recording, active-order position cap 10, fill reconciliation, SL/TP read-back, and shared workflow concurrency. Safety CI on the tested code revision: run `44160419914`, compile passed, 37/37 tests passed.
- PR #8 fixed the reserved Actions environment variable issue by using `FINAM_STATE_BRANCH`; merged to main (merge commit `579306da567aaa2733ffec98a4002306ae66d97b`). Both executor workflows pass the explicit branch. Safety CI run `44163272970`: compile passed, 38/38 tests passed.
- Actual GitHub Contents API integration passed in isolated test branch `test/finam-journal-validation`, run `44162894813`: reserve/read/update/read succeeded using Actions token with Contents:write. No Finam endpoint or broker order was used.
- PR #6 restored the read-only futures scanner workflow and was merged to main (merge commit `2337fda89ec7ab875444feaa240c67b2747121e`); validation run `44161381744` passed YAML structure and scanner compilation.
- PR #1 older executor draft is closed as superseded. PR #7 is validation-only and must not be merged. PR #2 and #3 remain Draft/open; preserve the AI Trainer experiment and avoid enabling a second scheduled Telegram notifier without checking duplication.
- Main workflows keep `FINAM_DRY_RUN` safe by default. Last verified effective value in CI: `true`. No real broker order was sent in this work.
- Live trading remains blocked: no demo-account end-to-end test is available; actual broker partial-fill/cancel/SLTP lifecycle is unverified; safe automatic recovery from unprotected exposure is not implemented. Do not set `FINAM_DRY_RUN=false` or dispatch live execution until these are independently resolved.

## 2026-11-18 — controlled live-test guardrails (PR pending)
- User confirmed no demo account is available and requested validation on the real Finam account. This is implemented as a controlled, manually dispatched mode rather than enabling the hourly schedule.
- Manual executor workflow now offers `DRY_RUN` (default) and `LIVE_ONE_MIN_LOT`. Live mode requires the repository variable `FINAM_DRY_RUN` to be exactly `false`, and first runs the read-only Finam account/instrument audit. Otherwise the job fails before executor start.
- Scheduled scanner+executor workflow is hard-pinned to `FINAM_DRY_RUN=true`, so enabling the manual live-test variable cannot accidentally turn every hourly/weekend schedule into live trading.
- Executor hard limit: at most one new broker-order POST per invocation. Attempt is counted before POST so ambiguous timeout cannot allow a second order in the same run.
- Existing `TEST_MODE_MIN_VOLUME=True` submits exactly one minimum trading lot, not one share. A minimum lot can still have substantial RUB value depending on the instrument; inspect instrument and notional before any live run.
- This is a guardrail, not proof of complete broker lifecycle safety. If SL/TP creation/read-back fails after a fill, current code alerts and halts; it does not automatically close exposure. Owner/operator must be available to inspect the account and intervene. Do not run unattended.
- PR branch `safety/manual-live-one-lot-gate-20261118`; pending CI and review. Until merged and a controlled manual workflow is explicitly selected, no live mode is enabled. Repository variable remains at last verified safe value `true`.

## 2026-11-18 — controlled manual live workflow merged
- PR #9 merged as `83eefa1aa40e340418e7f2672650fce8a2babbca`: explicit manual modes `DRY_RUN` (default) and `LIVE_ONE_MIN_LOT`; read-only Finam audit must pass first; live mode requires repo variable `FINAM_DRY_RUN=false`; scheduled MOEX scanner+executor is hard-pinned to `FINAM_DRY_RUN=true`; executor submits at most one new order POST per invocation. CI run `44225394589`: compile passed, 39/39 tests passed.
- PR #10 merged as `14bb119814e0a53773eb94168c388bec505ab97b`: manual workflow now runs `moex_edge_fast_33.py` to generate a fresh `moex_signals.csv` before calling executor; installs NumPy and uploads scanner output artifact. CI run `44225571966`: compile passed, 39/39 tests passed.
- Existing `TEST_MODE_MIN_VOLUME=True` means one full minimum trading lot (not one share); notional may be material and depends on instrument price and lot size.
- Latest CI confirmed `FINAM_DRY_RUN=safe` (true). No live order has been submitted. The manual live workflow has not been dispatched.
- Remaining live risk: if broker confirms a fill but SL/TP creation/read-back fails, executor alerts and halts; it does not automatically close exposure. Live runs must not be unattended; operator must be able to inspect account and manually intervene. This is not yet a fully self-recovering autonomous live system.
- Before first real run: owner deliberately changes repository variable `FINAM_DRY_RUN` to exact string `false`, then dispatches workflow `Finam Executor — controlled manual run` with mode `LIVE_ONE_MIN_LOT`. Do not change scheduled workflow; it remains pinned to dry-run.


## 2026-11-18 — zero-quantity Finam positions fix and validation
- User checked Finam manually and confirmed there are currently no open positions and no active orders (user-reported UI state; not independently queried from broker API in this session).
- Investigated why executor still logged 1 open instrument in DRY_RUN run `44238708231`. The previous code counted every `account_data["positions"]` record with a symbol, even if Finam's signed `quantity.value` was zero.
- PR #11 merged to main: https://github.com/vkazarin763-cloud/moex-edge-fast1/pull/11 ; squash merge commit `d8d87051d423013b2ca7d1c55cb677334a322760`.
- New helper `get_open_position_symbols(account_data)` counts only non-zero signed quantities. It fails closed on malformed position lists, missing symbols, or missing/invalid quantity. No strategy, signal rules, lot size, live-mode settings, or order submission behavior was changed.
- Added four tests: zero-quantity records ignored; empty positions list; missing quantity rejected; malformed positions response rejected.
- GitHub Actions run `44240882740` completed SUCCESS: Python compilation passed; all 43 unit tests passed. Relevant new tests all passed.
- Main branch file `finam_executor.py` verified to contain the merged helper and use it in `main()`.
- Next mandatory step: manually dispatch `Finam Executor — controlled manual run` in `DRY_RUN` mode only. Check fresh scanner output and confirm executor logs `Открытых позиций: 0/10` (or exact zero count) and no false occupied-symbol skip. Do not dispatch LIVE until this dry-run is reviewed and the actual broker state is independently reconciled.
- Important state distinction: the user previously set repository variable `FINAM_DRY_RUN=false` for a manual live test; one prior run `44234763883` confirmed it was false, but submitted no order because there were no confirmed signals. The scheduled workflow is hard-pinned to dry-run. Do not infer the current repository variable value without a fresh safe check.
- Previous manual run `44238708231` was DRY_RUN, audit succeeded, but executor logged 1 open position; it prepared DOMRF without submitting and skipped T because a position was already counted. That run predates PR #11.
- No new broker order was submitted by PR #11, its CI, or the merge. The next run must remain DRY_RUN.


## 2026-11-18 — controlled live-trial request; latest DRY_RUN checkpoint

- User asked to record the latest result and proceed with a real-mode trial for one day. This is an explicit request for live trading, but it does not mean a live workflow has already been dispatched or that any order has been submitted.
- Latest verified workflow run: `44253089210`, completed SUCCESS on main at commit `60f30705bacfe81fcbc990aa4cc41e8d3027e38a`.
- Read-only Finam preflight passed: authentication/account read OK; valid lot and tick metadata 44/44; LONG/SHORT permissions 44/44; no instrument audit errors; no blocked tickers.
- Fresh scanner signals: DOMRF LONG (Donchian55), H1 confirmed; T LONG (Keltner), H1 confirmed.
- Executor reported 0 open positions out of 10. Environment explicitly had `FINAM_DRY_RUN=true`; both signals were prepared in dry-run only; no broker order endpoint was called and no order was submitted.
- Executor reported `trade_lot_size=1` and prepared quantity 1 share for both DOMRF and T. Scanner printed risk-sized quantities of 1 DOMRF and 11 T. This is a sizing-source mismatch that must remain visible in trial review; do not interpret scanner quantity as the executor's live quantity. Scanner/executor SL/TP for T also differed slightly due to rounding.
- Artifact `manual-moex-signals` uploaded for 7 days: run artifact ID `14404369409`.
- Live-trial guardrails remain: manual workflow choice must be explicitly `LIVE_ONE_MIN_LOT`; read-only audit must pass; at most one new order per workflow run; minimum full exchange lot; maximum 10 open positions; scheduled scanner workflow remains hard-pinned to DRY_RUN. A single manual workflow dispatch is not a continuous all-day service; further executions require separate manual dispatches unless a separately reviewed schedule is configured.
- No live dispatch was performed by the assistant. The current repository variable `FINAM_DRY_RUN` was not re-read in this checkpoint; the successful run above explicitly used true.
- Before each live dispatch, independently verify Finam has no unexpected open positions/orders and confirm the instrument's actual minimum lot and available funds. If any order outcome is ambiguous or protection (SL/TP) is not confirmed, stop further runs and reconcile in Finam manually. Never blindly retry an ambiguous order.


## 2026-11-18 — critical live SL/TP failure and safety suspension

- Manual live workflow run: https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/44258781684
- Verified executor log: FINAM_DRY_RUN=false; market order for T@MISX was accepted by Finam as order_id=1289574, client_order_id=466e17984f174fc3bd2d; executor logged 1 share as open.
- Immediately afterwards PlaceSLTPOrder returned HTTP 400, code 3, message [666]: "An uncovered position may arise/increase". No SL/TP protection was confirmed. The user subsequently reported seeing one T share in the Finam portfolio and then reported manually closing it. The sale fill and final account/order state have NOT been independently verified through the broker API; do not state that the account is reconciled until a read-only check confirms zero T quantity and no residual active orders.
- The workflow job conclusion SUCCESS did not mean the trade was safely protected; it only meant the script completed and reported the critical exception.
- Official Finam REST docs describe SLTP side as the side for both legs and show a SIDE_BUY example with a lower SL and higher TP (long-position shape). Existing executor sent SIDE_SELL for LONG. This is a strong code-level suspect for error [666], but not yet broker-confirmed. No live API test is permitted to prove it.
- A separate safety branch `safety/disable-live-until-sltp-audit-20261118` now proposes: (1) LONG SLTP side=SIDE_BUY / SHORT=SIDE_SELL; (2) read-back validation against that protected-position side; (3) code-level second live kill-switch requiring FINAM_LIVE_TRADING_ENABLED=true in addition to FINAM_DRY_RUN=false; (4) manual executor workflow pinned to DRY_RUN only; (5) unit tests for both side mappings and the kill-switch.
- These changes are on a draft PR branch only; they are NOT merged into main. They have not yet passed CI and have not been validated against a broker sandbox. The live workflow must remain suspended. Do not set or rely on FINAM_LIVE_TRADING_ENABLED; do not run LIVE mode.
- The repository Actions variable FINAM_DRY_RUN was not re-read or changed during this work. Manual workflow is pinned to true in the proposed branch; scheduled workflow was already pinned to true. Code-level gate blocks direct live execution unless the separate second variable is explicitly true.
- User reported that the T position was manually closed. Treat this as user-reported only; verify via read-only Finam account/orders before resuming any executor.
- No strategy, scanner signals, AI Trainer, virtual portfolio, futures workflow, secrets, or repository variables were changed.
