# Changelog MOEX EDGE

## 2026-11-16
- **ИСПРАВЛЕН КРИТИЧЕСКИЙ БАГ в `ai_agent.py`:**
  - Устранен баг «путешествия во времени» (стопы проверялись на свечах, которые были ДО времени входа).
  - Устранен баг дублирования позиций (агент открывал по 3-4 сделки на один тикер после срабатывания стопа).
  - Время входа теперь фиксируется по часовой свече, а не по дневной (00:00).
  - Добавлен запрет на повторный вход в тикер в течение одного дня.
- Настроен внешний планировщик `cron-job.org` (HTTP POST, API GitHub, workflow_dispatch).
- Подтверждена работа Telegram-уведомлений (приходят отчеты о закрытии сделок).
- Добавлены файлы памяти проекта.

## 2026-11-15
- Аудит репозитория. Изменений кода нет.

## 2026-11-17 — AI Virtual Agent restored
- Исправлена область видимости `get_kelly_pct` в `ai_agent.py`: функция была недоступна из `main`, что вызывало `NameError` при обработке сигнала.
- Добавлены unit-тесты Kelly и GitHub Actions workflow для компиляции AI Agent/Trainer и тестирования функции.
- Не менялись AI Trainer, портфель, веса, торговые правила и расписание.

## 2026-11-17 — Finam Executor Telegram notifications
- Добавлена передача `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID` в окружение Finam Executor в почасовом и ручном GitHub Actions workflow.
- Режим `FINAM_DRY_RUN`, торговая логика и расписание не изменялись.

## 2026-11-17 — Finam Executor safety hardening (Draft PR)
- Добавлены client_order_id, сверка после неоднозначной отправки, ожидание терминального статуса и проверка фактических сделок.
- Защитные SL/TP рассчитываются по VWAP фактических исполнений и выставляются только на подтверждённое количество.
- Добавлены mock unit-тесты и CI workflow.
- Оба workflow передают `FINAM_DRY_RUN` из Actions Variable с default `true`; некорректное значение блокирует запуск.
- Реальные заявки не отправлялись; main и секреты не менялись.

## 2026-11-17 — AI handoff
- Добавлен `HANDOFF_FOR_NEXT_AI.md` с текущим состоянием MOEX EDGE и инструкциями безопасного продолжения.
- Документированы статусы PR, CI (10/10 mocked tests), ограничения реальной торговли и следующие проверки.

## 2026-11-17 — Finam Executor follow-up audit
- Проверены публичные REST/protobuf контракты Finam для заявок, сделок, параметров инструментов и SL/TP.
- Усилена проверка ответа PlaceSLTPOrder: HTTP 200 без подтверждённого order_id и sltp_order больше не считается успехом.
- Добавлено округление защитных цен по фактическому min_step/decimals или price_step инструмента.
- Добавлены unit-тесты для SL/TP подтверждения и ценовых шагов.
- Последний CI run, подтверждённый как успешный, относится к предыдущему SHA; результат CI для последнего кода пока не подтверждён.
- Реальные заявки не отправлялись; main, секреты и FINAM_DRY_RUN не менялись.

- CI follow-up: run 44141464912 успешно; Python compile и 14/14 unit-тестов прошли. Проверки mock-only, брокерские API-вызовы и реальные сделки не выполнялись.

## 2026-11-17 — Finam configuration and permissions audit
- Safety CI проверяет наличие Finam/Telegram secrets без печати значений; все четыре обязательных секрета обнаружены.
- Эффективный FINAM_DRY_RUN=safe, боевой режим не включён.
- Добавлена проверка account-specific разрешений LONG/SHORT перед отправкой заявки.
- CI run 44141866777: компиляция успешна, 16/16 unit-тестов пройдены. Реальные API-запросы и заявки не выполнялись.

## 2026-11-17 — read-only Finam audit and position limit
- Добавлен read-only аудит Finam: авторизация, GET счёта, торговые параметры и шаг цены для 44 тикеров.
- Последний успешный аудит: 44/44 лот/шаг цены, 44/44 LONG, 44/44 SHORT; 0 ошибок. Предыдущий проход кратковременно показывал 43/44 SHORT; проверка направления выполняется перед каждой заявкой.
- Добавлен жёсткий лимит MAX_OPEN_POSITIONS=10 и unit-тесты.
- Оставлен TEST_MODE_MIN_VOLUME=True (один минимальный лот).
- CI run 44143462329: compile success, 19/19 tests passed. Secrets present, effective FINAM_DRY_RUN=safe.
- Выполнялись только read-only API запросы; order endpoints не вызывались, реальные сделки не совершались.

- После успешного read-only аудита workflow переведён на ручной запуск (workflow_dispatch), чтобы не повторять массовые GET-запросы при каждом обновлении PR и не создавать лишнюю нагрузку на лимиты Finam.

## 2026-11-17 — fill reconciliation and SL/TP read-back
- Добавлен retry/polling истории сделок до точного совпадения с executed_quantity (10 попыток).
- Добавлен GetOrder read-back после SL/TP POST с проверкой активного статуса, отсутствия срабатывания, order_id, symbol, side, quantities и prices.
- Скрыты баланс и список открытых инструментов в workflow logs.
- CI run 44144452367: compile success, 24/24 tests passed; secrets present, FINAM_DRY_RUN=safe.
- Read-only Finam audit 44143080070 успешен; реальные заявки не отправлялись.

## 2026-11-17 — active order position-cap hardening
- Лимит MAX_OPEN_POSITIONS=10 теперь учитывает активные заявки вместе с открытыми позициями.
- Неизвестные статусы активных заявок резервируют слот; ошибка чтения списка заявок блокирует новые заявки.
- Добавлены unit-тесты. CI run 44156645285: compile success, 27/27 tests passed.
- Secrets присутствуют; FINAM_DRY_RUN=safe. Реальные заявки не отправлялись.

 
## 2026-11-17 — SL/TP ambiguity and signal-safety follow-up
- SL/TP заявки теперь получают собственный client_order_id; при timeout/5xx/408 выполняется сверка через GetOrders по client_order_id и GetOrder. Повторный POST не выполняется.
- Для SL/TP явно задаются SLTP_QTY_MEASURE_VALUE (количество в штуках), а не процент от позиции.
- Активная заявка без символа теперь блокирует новые отправки (fail closed).
- Любая непредвиденная ошибка после отправки рыночной заявки вызывает критическое Telegram-уведомление и останавливает обработку следующих сигналов.
- CI run 44157773263: compile success, 30/30 unit tests passed; все обязательные secrets present; FINAM_DRY_RUN=true.
- Отдельный аудит выявил незакрытые production-вопросы: нет подтверждённого демо-интеграционного теста полного цикла; нет автоматического безопасного восстановления/закрытия позиции при неподтверждённой защите; executor не хранит постоянный идентификатор уже обработанного сигнала, поэтому после закрытия позиции повторный вход по всё ещё активному CSV-сигналу не исключён.
- Реальные заявки не отправлялись; main, secrets и FINAM_DRY_RUN не менялись.

## 2026-11-17 — Finam signal idempotency follow-up
- Wired durable signal-state access into the scheduled scanner/executor workflow using the Actions runtime token and least-privilege contents-write permission.
- Serialized scheduled and manual executor workflows under one concurrency group.
- Recorded terminal no-fill order outcomes and reset per-row signal identifiers.
- Pending CI verification on the latest PR #5 head. No live workflow dispatch or broker order was performed.

## 2026-11-17 — CI syntax regression and correction
- CI run `44160110042` exposed a SyntaxError in `tests/test_finam_executor.py`: three line continuations contained two literal backslashes. Python compilation of production modules passed, but test discovery failed while importing the test module.
- Corrected the three continuations and added mocked tests for reading and writing the GitHub Contents API signal journal, including SHA-based updates and branch selection.
- Latest observed safety CI run: `44160419914`; dependency install and configuration-presence check passed, Python compile passed, unit tests were still running at last inspection. Do not report the latest suite as green until the run completes.
- Initialized `finam_signal_state.json` as an empty object on the PR branch.
- No real broker order or executor workflow dispatch was performed. Effective `FINAM_DRY_RUN=true`.

## 2026-11-17 — latest verified safety CI after signal journal fixes
- Safety CI run `44160419914` completed successfully on PR merge commit `78f3a81`, which includes branch commit `682493b470758e26e4eb63355770d7633dfe0be0`.
- Python compilation passed; `37 tests` ran and all passed (`OK`). This includes the mocked GitHub Contents API journal read/write tests.
- Configuration check confirmed `FINAM_API_SECRET`, `FINAM_ACCOUNT_ID`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID` are present (values masked); effective `FINAM_DRY_RUN=true`.
- Later commits after this run only update journals/handoff documentation; the executor code and test file tested by this run are unchanged.
- CI run details: https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/44160419914

## 2026-11-17 — Finam signal journal branch fix
- Fixed GitHub Actions branch selection by introducing `FINAM_STATE_BRANCH` instead of trying to override reserved `GITHUB_REF_NAME`.
- Both executor workflows now pass the explicit state branch. Added a unit test for branch override precedence.
- Isolated real GitHub Contents API read/write integration passed with the Actions token on a test branch; no Finam/broker calls.

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
