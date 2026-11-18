# Журнал решений MOEX EDGE

## 2026-11-15
- Решено: MOEX EDGE FAST — боевой режим, реальные заявки задуманы. Не отключать.
- Решено: AI Agent — только виртуальный трейдер, реальных заявок не шлёт. Собираем статистику месяц.

## 2026-11-16
- Решено: подключить внешний планировщик `cron-job.org` из-за пропусков запусков встроенным cron GitHub Actions.
- Решено: завести внешнюю память проекта (файлы .md и STARTER_PROMPT.txt).
- **Решено (критично):** Исправить баг в `ai_agent.py`, связанный с дублированием сделок и неверной проверкой времени входа. Это не оптимизация стратегии, а базовая защита риск-менеджмента.
  - *Результат:* Портфель очищен от «мусорных» дублей (первые закрытые сделки по ALRS в статистике — это хвост старого бага).
  - *Дальше:* Начинаем сбор статистики с чистой логикой (1 тикер = 1 сделка в день, стопы проверяются только после входа).
- Замечено: ai_trainer дал вес 10 стратегии EMA20/50 (10 сделок) и вес 8 Morning_Star (8 сделок). Риск шума. Наблюдаем, не правим.
## 2026-11-17
- **ПРОВЕДЕН БЭКТЕСТ ПРИНЦИПОВ ВХОДА И ВЫХОДА (2 года, 10 акций):**
  - Текущая логика (TP 5%, SL 3%) УБЫТОЧНА: -309% за 2 года.
  - Лучшая логика: Вход по пробою Donchian55 + Частичная фиксация (50% на +3%, остаток по трейлингу 2 ATR). Общая доходность: +629%, Винрейт: 48%.
  - Фильтр по ATR для входа (Multi) не улучшает результат, только сокращает число сделок. Оставляем Single.
  - **Решение:** После сбора текущей статистики перевести `ai_agent.py` на логику `PARTIAL` (частичная фиксация + ATR-трейлинг).
## 2026-11-17 (Вечер)
- **ПРОВЕДЕН ГЕНЕРАЛЬНЫЙ БЭКТЕСТ (Grid Search):**
  - Найдена идеальная связка за 2 года: Вход по пробою Donchian55 с фильтром EMA200 (TrendFilter) + Частичная фиксация 50% на +5%, остаток по трейлингу 2.0 ATR. Итог: +648% за 2 года, Винрейт 42%, средняя сделка +0.72%.
  - Текущая логика бота (Fixed 5%) показала худший результат: -309%.
  - Быстрая фиксация (на +1.5% или +3%) режет прибыль.
  - **Решение:** После окончания сбора текущей статистики полностью перевести `ai_agent.py` на связку `TrendFilter` + `Partial_5.0`.
## 2026-11-17 (Ночь)
- **ПРОВЕДЕН OUT-OF-SAMPLE ТЕСТ (2022-2023):**
  - Связка `TrendFilter Partial_5.0` (лидер 2024-2026) показала МИНУС (-21%). Подтверждена переподгонка.
  - Связка `Single Trail_2.0` (Donchian55 + ATR-трейлинг) показала ПЛЮС (+142%) в 2022-2023 и (+320%) в 2024-2026.
  - **Решение:** Для версии 2.0 использовать ТОЛЬКО `Single Trail_2.0`. Никаких фильтров EMA200 и фиксированных тейков.

## 2026-11-17 — восстановление AI Virtual Agent
- Найдена причина отказа агента: `get_kelly_pct` была локальной функцией внутри `sigs` и недостижима из `main`; вызов после обнаружения сигнала приводил к `NameError`.
- Исправление внесено в `main`: функция Kelly вынесена на уровень модуля, математика и торговые правила сохранены.
- Добавлены unit-тесты и автоматический workflow проверки синтаксиса/тестов.
- Виртуальный портфель и веса не переписывались; ручной запуск, способный изменить виртуальный портфель, не выполнялся.

## 2026-11-17 — подключение Telegram к Finam Executor
- Решено передавать `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID` из GitHub Actions Secrets в окружение Finam Executor в почасовом и ручном workflow.
- Изменение не включает/не отключает реальную торговлю: `FINAM_DRY_RUN` и торговая логика остаются без изменений.
- Для снижения риска изменение вынесено в отдельную ветку и отдельный PR, без объединения более широкого PR с исправлениями исполнения ордеров.
- Перед ожиданием уведомлений необходимо подтвердить наличие secrets с точными именами в Settings → Secrets and variables → Actions.

## 2026-11-17 — усиление Finam Executor (Draft PR)
- Решено исправить неоднозначную отправку рыночных заявок: `client_order_id`, сверка результата, запрет слепого повторения POST.
- SL/TP должны рассчитываться от подтверждённой средней цены исполнения и выставляться только на реально исполненное количество.
- В обоих workflow режим `FINAM_DRY_RUN` передаётся из GitHub Actions Variable; значение по умолчанию — `true`. Неизвестные значения должны завершать процесс с ошибкой.
- Изменения изолированы в Draft PR. Не менять секреты, не запускать боевые заявки и не сливать в main до CI и аудита API.

## 2026-11-17 — передача контекста другой ИИ
- Источник передачи: `HANDOFF_FOR_NEXT_AI.md` в feature-ветке PR #5.
- Передача включает состояние Finam Executor, Signal Bot, AI Agent/Trainer, PR #1/#3/#4/#5, CI evidence и неразрешённые вопросы.
- Никакие секреты и реальные торговые данные в handoff не включать.
- PR #5 остаётся Draft; включение реальной торговли отложено до завершения аудита брокерского API и отдельного контролируемого решения владельца.

## 2026-11-17 — дополнительная проверка Finam API
- Решено не считать HTTP 200 от SL/TP подтверждением защиты: код должен проверить возвращённый order_id, объект sltp_order, статус и фактические параметры SL/TP.
- Решено использовать фактический шаг цены инструмента из GetAsset (min_step/decimals либо price_step), а не округление до двух знаков.
- Новые проверки и тесты изолированы в Draft PR #5. До CI на актуальном SHA, проверки секретов/Actions Variable и подтверждения account-specific API поведения боевой режим не включать.

- CI для follow-up hardening завершился успешно: run 44141464912, 14 тестов пройдены. Это подтверждает unit-сценарии и синтаксис, но не является интеграционным тестом с Finam и не разрешает автоматически включать live.

## 2026-11-17 — проверка конфигурации и разрешений
- Решено добавить в safety CI проверку присутствия обязательных секретов без вывода их значений.
- Подтверждено: четыре обязательных секрета присутствуют; эффективный режим FINAM_DRY_RUN=safe.
- Добавлена блокировка LONG/SHORT, если Finam account-specific параметры не подтверждают соответствующее разрешение.
- CI: run 44141866777, 16 тестов успешно. Это не broker integration test; live по-прежнему не включать до проверки реального API поведения и защитных сценариев.

## 2026-11-17 — read-only Finam validation and live risk limits
- Read-only API check confirms account access and 44/44 valid lot/tick metadata. Latest pass showed LONG 44/44 and SHORT 44/44; earlier pass showed 43/44 SHORT, so permissions are checked at order time.
- No order endpoint was called during this audit. No real trades were sent.
- Enforce maximum 10 concurrent account positions and retain one-minimum-lot mode. These constraints are part of live readiness.
- Latest CI run 44143462329 passed 19 tests; runtime secrets are present and FINAM_DRY_RUN remains safe.
- Keep PR #5 Draft and do not enable live until SL/TP lifecycle and orphan-exposure handling receive final review.

## 2026-11-17 — финальное подтверждение исполнения и защиты
- До выставления SL/TP обязательно дождаться совпадения объёма в истории сделок с executed_quantity (до 10 read-only попыток).
- После POST SL/TP обязательно читать заявку через GetOrder и сверять активный статус, symbol, side, количество и цены. Triggered/rejected/unknown состояния считаются критическими и останавливают обработку.
- Не выводить в CI баланс и список открытых бумаг; сохранять только агрегированные логи.
- CI run 44144452367 прошёл 24 теста; read-only account audit 44143080070 успешен. Live остаётся выключен до реального/демо подтверждения SL/TP lifecycle и контролируемой активации.

## 2026-11-17 — резервирование лимита активными заявками
- Лимит 10 теперь учитывает как открытые позиции, так и символы активных заявок из Finam GetOrders.
- Неизвестные статусы считаются активными; если список заявок недоступен/повреждён, запуск прекращается без новых заявок.
- Проверки покрыты тестами; CI run 44156645285: 27/27.
- Не включать live: интеграционные проверки жизненного цикла SL/TP и сценариев частичного исполнения ещё не подтверждены на sandbox.

 
## 2026-11-17 — неоднозначный результат SL/TP и контроль повторных сигналов
- Для SL/TP добавлен отдельный client_order_id; при сетевой ошибке/HTTP 5xx/408 выполняется только read-only reconciliation через список заявок и GetOrder, без повторного POST.
- Объёмы SL и TP явно задаются как SLTP_QTY_MEASURE_VALUE (штуки). Это соответствует enum Finam; значение по умолчанию также VALUE.
- Активная заявка без распознанного тикера считается критической ошибкой и блокирует новые заявки.
- Любое непредвиденное исключение после отправки рыночной заявки должно вызывать критическое уведомление и прекращать текущий запуск.
- Несмотря на 30/30 mocked tests, live запрещён до демо-проверки полного жизненного цикла и решения проблемы orphan exposure.
- Обнаружен риск повторного входа: CSV содержит ticker/direction/strategy/date/entry_price/qty, а executor не хранит долговременный журнал обработанных сигналов. Пока не добавлена/не проверена идемпотентность сигнала, повторный вход после закрытия позиции возможен.
- PR #5 остаётся Draft/open; main и FINAM_DRY_RUN не менялись.

## 2026-11-17 — signal journal safety decisions
- The persistent GitHub signal journal is authoritative in live mode; missing token/repository, unreadable/corrupt state, or failed write must stop order submission (fail closed).
- Signal reservation must be committed before the market-order POST. A reservation remains consumed after an ambiguous result; manual reconciliation is required rather than blind retry.
- A terminal order with zero execution is recorded as `NO_FILL_TERMINAL`; the signal is still not automatically retried while the same signal remains active in CSV.
- Both workflows that can run the executor share concurrency group `finam-executor-account` to prevent simultaneous read-modify-write updates to the state journal.
- These controls do not establish full broker lifecycle safety. Live activation remains disabled until orphan-exposure recovery and broker integration risks are resolved.

## 2026-11-17 — verified signal-journal CI
- Run `44160419914` succeeded on PR merge commit `78f3a81` (branch code/test commit `682493b470758e26e4eb63355770d7633dfe0be0`): compile passed, 37/37 unit tests passed, including mocked GitHub Contents API journal read/write tests.
- All four required Actions secrets were reported present without exposing values; effective `FINAM_DRY_RUN=true`.
- Subsequent branch commits only changed project journals/handoff/PR description; tested executor code and test file were unchanged.
- PR #5 remains Draft/open/unmerged. No executor workflow was dispatched and no real broker order was sent.
- Live blockers remain: no demo account/full order lifecycle integration test, no safe automatic recovery from unprotected exposure, and actual Actions-token journal write still needs a non-trading workflow verification.

## 2026-11-17 — journal branch environment
- Do not attempt to override GitHub's built-in `GITHUB_REF_NAME`; use a distinct `FINAM_STATE_BRANCH` variable for the branch where the durable state file should be read/written.
- In schedule and workflow_dispatch contexts, set it from `${{ github.ref_name }}`. In PR-only integration checks, use the pull request head branch explicitly.
- A live-token, no-broker GitHub Contents API integration check passed on a dedicated test branch. No broker endpoint was invoked.

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
