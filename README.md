# UBT: universal backtester for MT5 Expert Advisors

UBT is one toolkit for any MT5 strategy:

| Part | What it does | Command |
|---|---|---|
| **Data taker** | Asks for your MT5 account, password and server. Downloads the longest available **tick** and **OHLCV** history for the assets marked in the EA, purifies it, saves it and writes a quality report. | `python -m ubt download` |
| **Universal backtester** | Runs a Python port of the EA on a simulated MT5 trade server. The broker emulation follows the MT5 tester rules. | `python -m ubt backtest` |
| **Optimiser** | Grid / random / Latin hypercube / genetic search, run in parallel with a cache. Reports the best settings, the **robust best** (plateau), parameter importance and **global survival %**. | `python -m ubt optimize` |
| **Sensitivity and survival** | One-at-a-time sweeps, joint ±5/10/20 % perturbation survival, cost stress, sub-period stability, one **robustness score**. | `python -m ubt sensitivity` |
| **Walk-forward and Monte Carlo** | Rolling in-sample/out-of-sample tests and walk-forward efficiency. Trade-sequence shuffle, bootstrap and skip, plus probability of ruin. | `python -m ubt walkforward`, `montecarlo` |
| **Full study** | All of the above in one run: an HTML report plus `best_settings.set` and `robust_best_settings.set` to load straight into MT5. | `python -m ubt full` |
| **MT5 tester driver** | Runs the **original, unmodified `.ex5`** in the real MT5 Strategy Tester and parses its report. It also checks deal-by-deal parity with the Python port. | `python -m ubt mt5test` |
| **Porting tool** | Turns a new `.mq5` into a draft Python port. Inputs, enums and `.set` files are read from the source, so nothing is typed by hand. | `python -m ubt port` |

Included strategies:

* `experts/Zscore_and_Levando_MIX.mq5` with its line-by-line port `strategies/zscore_levando_mix.py` (both engines: Grid Z-Score MR v3.2 and LeVanDo Cascade v4.10)
* `experts/MA_Cross_Example.mq5` with `strategies/ma_cross_example.py` (minimal example of the workflow)

---

## 1. Install

```bash
pip install -r requirements.txt        # numpy pandas pyarrow pyyaml matplotlib pytest (+ MetaTrader5 on Windows)
python -m pytest -q                    # 27 tests, about 30 s
```

Downloading data and running the real MT5 tester need **Windows with an MT5 terminal installed**, because the official
`MetaTrader5` package only exists there. Everything else runs anywhere, on the downloaded data.

## 2. Download data (the data taker)

```bash
python -m ubt download --mq5 experts/Zscore_and_Levando_MIX.mq5
#   MT5 account (login number): 12345678
#   MT5 server (as shown in the terminal, e.g. Exness-MT5Real8): ...
#   MT5 password (not stored): ********
```

* The **assets are taken from the EA's inputs** (`InpGZ_Symbol`, `InpLV_Symbol`, so `BTCUSD`). Add more with
  `--symbols XAUUSD,EURUSD`. Broker suffixes are resolved automatically (`BTCUSD` → `BTCUSDm`).
* **Ticks:** from the earliest tick the broker serves up to now. They are fetched day by day, purified, and saved as one parquet
  file per month. The download is **resumable**: months already on disk are skipped. Use `--refresh` to re-download.
* **OHLCV:** M1, M5, M15, M30, H1, H2, H4, D1, W1 and MN1 from the earliest available bar (`--timeframes` to change).
  Bars are also **rebuilt from the purified ticks** and compared with the broker's bars.
* **Purification:** removes only provably bad records: non-positive or NaN prices, crossed quotes, exact duplicates,
  out-of-order ticks, absurd spreads, and isolated spikes that revert within a few ticks. It fixes OHLC
  inconsistencies and reports gaps. Real fast moves are kept.
* The password is read with `getpass` (or the `UBT_MT5_PASSWORD` environment variable) and is **never written to disk**.
* Set *Tools → Options → Charts → Max bars in chart* to **Unlimited** in the terminal, otherwise MT5 serves only that
  many bars per timeframe. Ticks are not affected.

Layout:

```
data/BTCUSD/symbol_spec.json            broker contract spec + broker-measured margin per lot
data/BTCUSD/account.json                leverage, stop-out levels, currency (no credentials)
data/BTCUSD/ticks/2024-01.parquet       time_msc, bid, ask, last, volume, flags
data/BTCUSD/bars/M1.parquet ...         broker OHLCV  (time, open, high, low, close, tick_volume, spread, real_volume)
data/BTCUSD/bars_from_ticks/M1.parquet  OHLCV rebuilt from ticks
data/BTCUSD/quality_report.json         what purification removed, gaps, broker-vs-ticks bar agreement
```

No MT5 at hand? `python -m ubt synth --root data` writes synthetic BTC-like data in the same format, so every
other command can be tried.

## 3. Backtest

```bash
python -m ubt backtest --config configs/zscore_levando.yaml --from 2024-01-01 --to 2024-03-01 --model real
python -m ubt backtest --config configs/zscore_levando.yaml --set my.set --param InpGZ_ZscorePeriod=20
```

Tick models, as in the MT5 tester:

| `--model` | Ticks | Use |
|---|---|---|
| `real` | real purified broker ticks | final confirmation (≈ "Every tick based on real ticks") |
| `every_tick` | ~12 synthetic ticks per M1 bar | middle ground |
| `m1_ohlc` | 4 ticks per M1 bar (O-L-H-C / O-H-L-C) | fast optimisation (≈ "1 minute OHLC") |

The output folder gets `report.html` (equity and drawdown chart, every metric, trades, inputs), `metrics.json`,
`deals.csv`, `trades.csv`, `equity.csv` (per minute, including intra-minute minimum equity) and `journal.log` (the
EA's own `Print` output).

**Metrics:** net profit, gross profit and loss, profit factor, expected payoff, trades, win rate, long and short
breakdown, largest win and loss, consecutive wins and losses, balance and equity drawdown (maximal and relative,
measured on every tick like MT5), recovery factor, MT5-style Sharpe, annualised Sharpe and Sortino, CAGR, Calmar,
return/DD, SQN, ulcer index, Z-score, AHPR and GHPR, LR correlation and standard error, profitable months %,
best and worst month, exposure, minimum margin level, stop-out / blown flags, and **`ontester`** (the EA's own
`OnTester()`).

## 4. Optimise, sensitivity, survival, full study

```bash
# everything at once: optimise -> robust best -> sensitivity/survival -> (walk-forward) -> final backtest -> Monte Carlo
python -m ubt full --config configs/zscore_levando.yaml --n 300 --final-model real --walkforward

# or step by step
python -m ubt optimize    --config configs/zscore_levando.yaml --method lhs --n 300
python -m ubt sensitivity --config configs/zscore_levando.yaml --params results/zscore_levando/optimization_summary.json
python -m ubt walkforward --config configs/zscore_levando.yaml --is-days 90 --oos-days 30
python -m ubt montecarlo  --trades results/zscore_levando/final_backtest/trades.csv
```

* **Parameter ranges:** `--space configs/zscore_levando_space.json` (curated), `--space auto` (±50 % around the EA's
  defaults, technical inputs like magic, comment and dashboard skipped), or an **MT5 `.set` file with optimisation
  ranges** (`name=value||start||step||stop||Y`), so a range set up in the MT5 tester can be reused.
* **Objective:** `ontester` (the EA's `OnTester`) by default, or any metric (`sharpe_annual`, `recovery_factor`, …) or
  expression, e.g. `--objective "net_profit / max(equity_dd_rel_pct, 1)"`.
* **Survival criteria:** `--min-trades`, `--min-pf`, `--max-dd`. "Profitable" means net profit > 0; "passed" means all
  criteria are met.

What you get:

| Output | Meaning |
|---|---|
| `best` | highest objective among passing sets |
| `robust_best` | best **neighbourhood average** (±1 grid step in every parameter): a plateau, not a spike |
| `global_survival_profitable_pct` / `_passed_pct` | % of all tested sets that are profitable / pass the criteria |
| `importance` | share of objective variance explained by each parameter |
| OAT sensitivity | per parameter: objective range, **sensitivity index**, **elasticity** at the chosen value, **survival %** across its range |
| Neighbourhood survival | all parameters perturbed **together** by ±5/10/20 %: survival %, pass %, median/P5/P95 objective, ratio to base |
| Cost stress | spread ×1, 1.5, 2, 3 and slippage 0, 10, 50 points: survival % |
| Period stability | same settings on K sub-periods: % profitable periods |
| `robustness_score` | 0–100 weighted survival (neighbourhood 35 %, OAT 25 %, costs 20 %, periods 20 %) |
| Walk-forward | OOS profit per window, % profitable windows, WFE, parameter changes |
| Monte Carlo | P5/P50/P95 profit and max DD, probability of loss and of ruin (shuffle, bootstrap, skip 10 %) |

Runs are parallel (`workers: 0` = all cores but one) and **cached** in `cache.jsonl`, so an interrupted or repeated
study resumes instantly. `best_settings.set` and `robust_best_settings.set` load directly into MT5.

## 5. The same EA: how fidelity is ensured

The port keeps the **MQL5 code structure**: every function has the same name and statement order, and globals become
`self.` attributes with the same names. It runs on an MQL5 emulation layer (`ubt/mql5`):

* `OrderSend` / `CTrade` / `CPositionInfo` / `COrderInfo` with MT5 retcodes and `GetLastError` values (4753, 4756, …);
  a position's ticket equals the opening order's ticket; selections are snapshots, as in MQL5;
* the trade server checks pending orders and SL/TP **before** `OnTick` on every tick. Buys close on Bid and sells on
  Ask, with MT5 trigger rules, stop-level and freeze-level validation, volume checks, margin from the broker's own
  `order_calc_margin`, stop-out, swaps at rollover (triple day), commission and slippage;
* bars are built from Bid ticks on every timeframe, and the forming bar (shift 0) updates live;
* `iMA`, `iStdDev`, `iATR`, `iRSI`, `iBands` and `iMACD` use the formulas **and warm-up conventions** of the MetaQuotes
  reference indicators;
* history before the start date is preloaded (`warmup_days`), like the tester.

Two independent checks are included:

1. **Transpiler versus hand port:** the auto-generated port of `Zscore_and_Levando_MIX.mq5` (3 flagged lines fixed)
   produces **deal-for-deal identical** results to the hand-written port (11,475 deals over 6 weeks, including cap-OUT
   closes, chain gaps, trailing and cascades). The test suite checks this on every run.
2. **Python versus the real MT5 tester:** run the original EA in MT5 and compare deals:

   ```bash
   python -m ubt backtest --config configs/zscore_levando.yaml --from 2024-01-01 --to 2024-02-01 --model real --out results/py
   python -m ubt mt5test --terminal "C:\Program Files\MetaTrader 5\terminal64.exe" ^
       --data-dir "%APPDATA%\MetaQuotes\Terminal\<id>" --expert Zscore_and_Levando_MIX.ex5 ^
       --mq5 experts/Zscore_and_Levando_MIX.mq5 --symbol BTCUSD --tf M5 --from 2024-01-01 --to 2024-02-01 ^
       --model real --parity-with results/py
   ```

   This prints `match_pct` and the first differing deal, if there is one.

**Known, documented differences:**

* MT5 synthetic "every tick" generation is proprietary, so `every_tick`/`m1_ohlc` here are approximations. Use
  `real` for parity checks.
* Profit conversion uses the broker's tick value at download time. This is exact when the profit currency is the
  account currency (BTCUSD on a USD account).
* Accounts are hedging (the EA requires hedging). Netting mode is not emulated.
* The tester's own spread and delay settings are not applied. Real ticks carry the real spread; `--spread-mult` and
  `--slippage` stress costs.
* Chart drawing (`Comment`, labels) is skipped. Its side-effecting call in `LV_UpdateDashboard` is kept.

**Speed:** the tick loop runs about 10–15k ticks/s per core in pure Python with this EA (both engines active). Use
`m1_ohlc` for wide optimisations, confirm with `real`, and let `workers` use all cores.

## 6. A new strategy with little manual coding

```bash
python -m ubt inputs --mq5 experts/MyEA.mq5 --write-set my_defaults.set --write-space configs/my_space.json
python -m ubt port   --mq5 experts/MyEA.mq5 --out strategies/my_ea.py
#   -> review the draft; search for TODO (usually a handful of lines)
python -m ubt backtest --strategy strategies/my_ea.py:MyEa --root data --symbol XAUUSD --tf H1 --from 2024-01-01 --to 2024-06-01
python -m ubt full     --strategy strategies/my_ea.py:MyEa --space configs/my_space.json --root data --symbol XAUUSD --tf H1
```

The transpiler converts procedural MQL5: enums, `#define` and `const`, structs, globals, `if`/`else`/`switch`/`for`/
`while`/`do`, ternaries, casts, `++`/`--`, integer division, `ArraySetAsSeries` → `as_series=True`, array
initialisers, in-place string functions, and `&` out-parameters, which are returned as tuples and unpacked at call
sites. Every function is syntax-checked. Anything it cannot convert becomes a stub with the original MQL5 beside it
and a `TODO`. Calls to out-parameter functions **inside** an expression are flagged for a one-line manual fix.
Classes with methods (OOP EAs) are not converted.

`experts/MA_Cross_Example.mq5` converts with **zero** manual edits, and its draft trades identically to
`strategies/ma_cross_example.py`.

Writing a port by hand is also simple: subclass `ubt.strategy.Strategy`, set `MQ5_FILE`, do
`from ubt.mql5 import *` and keep the MQL code. Pass output arrays as lists, and add `as_series=True` where MQL called
`ArraySetAsSeries(arr, true)`.

## 7. Layout

```
ubt/mql5/        constants, structs, MQL5 API functions, CTrade/CPositionInfo/COrderInfo
ubt/engine/      broker (trade server), bars, indicators, tick streams, terminal, backtest runner
ubt/data/        MT5 downloader, purification, parquet store, synthetic data
ubt/analysis/    metrics, parameter space, parallel evaluator, optimiser, sensitivity, walk-forward, Monte Carlo, reports
ubt/mt5_tester/  real MT5 tester driver + report parsers + parity check
ubt/mq5.py       .mq5 input/enum parser, auto ranges, .set read/write
ubt/transpile.py MQL5 -> Python draft port
strategies/      ported EAs
experts/         original .mq5 sources
configs/         study configuration and parameter ranges
tests/           pytest suite (synthetic data, no MT5 needed)
```
