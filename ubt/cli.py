"""Command line: ``python -m ubt <command> ...``  (run ``python -m ubt -h``)."""
from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import sys
from dataclasses import asdict, fields
from pathlib import Path

log = logging.getLogger("ubt")


# ---------------------------------------------------------------------- config helpers
def _load_yaml(path):
    if not path:
        return {}
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _auto_val(s):
    from .mq5 import _auto_val as av
    return av(s)


def _common(p: argparse.ArgumentParser):
    g = p.add_argument_group("strategy / data")
    g.add_argument("--config", help="YAML with defaults (see configs/zscore_levando.yaml)")
    g.add_argument("--strategy", help="module:Class or path.py:Class of the ported EA")
    g.add_argument("--root", dest="data_root", help="data folder (default data)")
    g.add_argument("--symbol")
    g.add_argument("--tf", dest="timeframe", help="chart timeframe, e.g. M5")
    g.add_argument("--from", dest="start")
    g.add_argument("--to", dest="end")
    g.add_argument("--model", choices=["real", "every_tick", "m1_ohlc"])
    g.add_argument("--deposit", type=float)
    g.add_argument("--leverage", type=int)
    g.add_argument("--commission", dest="commission_per_lot", type=float, help="per lot per side")
    g.add_argument("--slippage", dest="slippage_points", type=float)
    g.add_argument("--spread-mult", dest="spread_multiplier", type=float)
    g.add_argument("--warmup-days", dest="warmup_days", type=int)
    g.add_argument("--set", dest="set_file", help="MT5 .set file with input values (and optional ranges)")
    g.add_argument("--param", action="append", default=[], help="input override NAME=VALUE (repeatable)")
    g.add_argument("--workers", type=int)
    g.add_argument("--out", help="output folder")
    g.add_argument("-v", "--verbose", action="store_true")


def _criteria_args(p):
    g = p.add_argument_group("survival criteria")
    g.add_argument("--objective", help="metric name or expression (default ontester = EA's OnTester)")
    g.add_argument("--min-trades", type=int)
    g.add_argument("--min-pf", type=float)
    g.add_argument("--max-dd", type=float, help="max equity DD %% to count as passing")


def _space_args(p):
    p.add_argument("--space", help="JSON/YAML/.set range file, or 'auto' (from the .mq5 defaults)")
    p.add_argument("--only", help="comma list of inputs to optimise (with --space auto)")
    p.add_argument("--auto-spread", type=float, default=0.5, help="auto space: +-fraction around defaults")
    p.add_argument("--auto-points", type=int, default=5)


def _resolve(args):
    """Merge YAML config + CLI into (strategy_ref, cfg, inputs, extras)."""
    from .engine.backtest import BacktestConfig
    from .mq5 import read_set
    conf = _load_yaml(args.config)
    bt = dict(conf.get("backtest", {}))
    for f in fields(BacktestConfig):
        v = getattr(args, f.name, None)
        if v is not None:
            bt[f.name] = v
    if getattr(args, "verbose", False):
        bt["verbose"] = True
    known = {f.name for f in fields(BacktestConfig)}
    cfg = BacktestConfig(**{k: (str(v) if k in ("start", "end") else v) for k, v in bt.items() if k in known})
    strategy = args.strategy or conf.get("strategy") or "strategies/zscore_levando_mix.py:ZscoreLevandoMix"
    inputs = dict(conf.get("inputs") or {})
    set_space = {}
    set_file = getattr(args, "set_file", None) or conf.get("set")
    if set_file:
        vals, set_space = read_set(set_file)
        inputs.update(vals)
    for kv in getattr(args, "param", []) or []:
        k, v = kv.split("=", 1)
        inputs[k.strip()] = _auto_val(v)
    # keep only inputs the strategy knows (a .set may carry extra lines)
    from .analysis.runner import load_strategy
    cls = load_strategy(strategy)
    known_inputs = cls.defaults()
    if known_inputs:
        unknown = [k for k in inputs if k not in known_inputs]
        if unknown:
            log.warning("ignoring unknown inputs: %s", unknown)
        inputs = {k: v for k, v in inputs.items() if k in known_inputs}
    workers = args.workers if getattr(args, "workers", None) is not None else conf.get("workers", 0)
    return strategy, cls, cfg, inputs, conf, set_space, workers


def _space(args, conf, cls, set_space):
    from .analysis.space import ParamSpace
    from .mq5 import auto_space
    spec = getattr(args, "space", None) or conf.get("space")
    if spec in (None, "auto"):
        if set_space and spec is None:
            return ParamSpace(set_space)
        info = cls.mq5_info()
        if info is None:
            raise SystemExit("--space auto needs a strategy with MQ5_FILE")
        only = [s.strip() for s in (getattr(args, "only", None) or conf.get("only") or "").split(",") if s.strip()] or None
        return ParamSpace(auto_space(info, include=only, spread=getattr(args, "auto_spread", 0.5),
                                     points=getattr(args, "auto_points", 5)))
    if isinstance(spec, dict):
        return ParamSpace(spec)
    return ParamSpace.load(spec)


def _criteria(args, conf):
    from .analysis.runner import Criteria
    c = dict(conf.get("criteria") or {})
    if getattr(args, "min_trades", None) is not None:
        c["min_trades"] = args.min_trades
    if getattr(args, "min_pf", None) is not None:
        c["min_profit_factor"] = args.min_pf
    if getattr(args, "max_dd", None) is not None:
        c["max_dd_pct"] = args.max_dd
    return Criteria(**c)


def _objective(args, conf):
    return getattr(args, "objective", None) or conf.get("objective") or (conf.get("optimize") or {}).get("objective") or "ontester"


def _out(args, conf, default):
    return Path(getattr(args, "out", None) or conf.get("out") or default)


def _print_json(d):
    print(json.dumps(d, indent=2, default=str))


# ---------------------------------------------------------------------- commands
def cmd_inputs(args):
    from .mq5 import auto_space, parse_mq5, write_set
    info = parse_mq5(args.mq5)
    print(f"{'input':<30} {'type':<22} {'default':<18} comment")
    for p in info.inputs:
        print(f"{p.name:<30} {p.type:<22} {str(p.default):<18} {p.comment}")
    from .mql5.constants import TIMEFRAME_NAMES
    print("\nmarked assets:", info.symbols(), " timeframes:", [TIMEFRAME_NAMES[t] for t in info.timeframes()])
    if args.write_set:
        write_set(args.write_set, info.defaults(), None, info)
        print("wrote", args.write_set)
    if args.write_space:
        sp = auto_space(info, spread=args.auto_spread, points=args.auto_points)
        Path(args.write_space).parent.mkdir(parents=True, exist_ok=True)
        Path(args.write_space).write_text(json.dumps(sp, indent=2))
        print("wrote", args.write_space, f"({len(sp)} parameters)")


def cmd_download(args):
    from .data.mt5_downloader import run_download
    from .mq5 import parse_mq5
    symbols = [s.strip() for s in (args.symbols or "").split(",") if s.strip()]
    tfs = [s.strip().upper() for s in (args.timeframes or "").split(",") if s.strip()] or None
    if args.mq5:
        info = parse_mq5(args.mq5)
        for s in info.symbols():
            if s not in symbols:
                symbols.append(s)
    if not symbols:
        raise SystemExit("no symbols: pass --symbols or --mq5 (assets marked in the EA inputs)")
    login = args.login or input("MT5 account (login number): ").strip()
    server = args.server or input("MT5 server (as shown in the terminal, e.g. Exness-MT5Real8): ").strip()
    password = os.environ.get("UBT_MT5_PASSWORD") or getpass.getpass("MT5 password (not stored): ")
    print(f"downloading {symbols} ...")
    summary = run_download(int(login), password, server, symbols, args.root, tfs, args.start, args.end,
                           ticks=not args.no_ticks, bars=not args.no_bars, terminal_path=args.terminal,
                           refresh=args.refresh, chunk_hours=args.chunk_hours)
    _print_json(summary)


def cmd_synth(args):
    from .data.synthetic import build_store
    build_store(args.root, args.symbol, args.start, args.end, seed=args.seed)
    print(f"synthetic data for {args.symbol} written to {args.root}")


def cmd_backtest(args):
    from .analysis.metrics import format_metrics
    from .analysis.report import backtest_report
    from .engine.backtest import run_backtest
    strategy, cls, cfg, inputs, conf, _, _ = _resolve(args)
    res = run_backtest(cls, inputs, cfg)
    out = _out(args, conf, "results/backtest")
    res.save(out)
    backtest_report(res, out / "report.html", f"{cls.__name__} backtest")
    print(format_metrics(res.metrics))
    print(f"\n{res.ticks:,} ticks in {res.seconds:.1f}s -> {out}/report.html")


def _evaluator(strategy, cfg, inputs, workers, out):
    from .analysis.runner import Evaluator
    return Evaluator(strategy, inputs, cfg, workers or 0, out / "cache.jsonl")


def cmd_optimize(args):
    from .analysis.optimizer import optimize
    from .analysis.report import full_report
    strategy, cls, cfg, inputs, conf, set_space, workers = _resolve(args)
    space = _space(args, conf, cls, set_space)
    oc = conf.get("optimize") or {}
    out = _out(args, conf, "results/optimize")
    ev = _evaluator(strategy, cfg, inputs, workers, out)
    print(f"space: {len(space.names)} parameters, grid size {space.size():,}")
    opt = optimize(ev, space, args.method or oc.get("method", "lhs"), args.n or oc.get("n", 100),
                   _objective(args, conf), _criteria(args, conf), seed=args.seed)
    opt.save(out)
    full_report(out / "report.html", f"{cls.__name__} optimisation", f"{cfg.symbol} {cfg.start} → {cfg.end}", opt=opt)
    _print_json({"best": opt.best, "robust_best": opt.robust_best, "summary": opt.summary,
                 "importance": opt.importance})
    print(f"-> {out}/report.html")


def _base_params(args, conf, space, inputs, cls):
    base = {}
    if getattr(args, "params", None):
        p = Path(args.params)
        d = json.loads(p.read_text()) if p.exists() else json.loads(args.params)
        base = d.get("robust_best") or d.get("best") or d
    defaults = {**cls.defaults(), **inputs}
    return {n: base.get(n, defaults.get(n)) for n in space.names}


def cmd_sensitivity(args):
    from .analysis import sensitivity as S
    from .analysis.report import full_report
    strategy, cls, cfg, inputs, conf, set_space, workers = _resolve(args)
    space = _space(args, conf, cls, set_space)
    out = _out(args, conf, "results/sensitivity")
    ev = _evaluator(strategy, cfg, inputs, workers, out)
    sc = conf.get("sensitivity") or {}
    base = _base_params(args, conf, space, inputs, cls)
    tests = [t.strip() for t in (args.tests or ",".join(sc.get("tests", ["oat", "neighborhood", "costs", "periods"]))).split(",")]
    pcts = [float(x) for x in (args.pcts or ",".join(str(x) for x in sc.get("pcts", [5, 10, 20]))).split(",")]
    res = S.analyze(ev, space, base, _objective(args, conf), _criteria(args, conf), tests, pcts,
                    args.n_perturb or sc.get("n_perturb", 40), sc.get("max_points", 9), sc.get("periods", 4))
    res.save(out)
    full_report(out / "report.html", f"{cls.__name__} sensitivity & survival", f"{cfg.symbol} {cfg.start} → {cfg.end}",
                sens=res)
    _print_json(res.summary)
    print(f"-> {out}/report.html")


def cmd_walkforward(args):
    from .analysis.report import full_report
    from .analysis.walkforward import walk_forward
    strategy, cls, cfg, inputs, conf, set_space, workers = _resolve(args)
    space = _space(args, conf, cls, set_space)
    out = _out(args, conf, "results/walkforward")
    wc = conf.get("walkforward") or {}
    ev = _evaluator(strategy, cfg, inputs, workers, out)
    wf = walk_forward(ev, space, args.is_days or wc.get("is_days", 90), args.oos_days or wc.get("oos_days", 30),
                      args.method or wc.get("method", "lhs"), args.n or wc.get("n", 40), _objective(args, conf),
                      _criteria(args, conf), wc.get("pick", "robust"), args.anchored or wc.get("anchored", False))
    wf.save(out)
    full_report(out / "report.html", f"{cls.__name__} walk-forward", f"{cfg.symbol} {cfg.start} → {cfg.end}", wf=wf)
    _print_json(wf.summary)


def cmd_montecarlo(args):
    import pandas as pd
    from .analysis.montecarlo import monte_carlo, save_mc
    tr = pd.read_csv(args.trades)
    res = monte_carlo(tr, args.deposit, args.sims, ruin_dd_pct=args.ruin_dd)
    save_mc(res, Path(args.trades).parent)
    _print_json(res)


def cmd_full(args):
    """optimise -> pick robust best -> sensitivity/survival -> (walk-forward) -> final backtest -> Monte Carlo."""
    from .analysis import sensitivity as S
    from .analysis.montecarlo import monte_carlo
    from .analysis.optimizer import optimize
    from .analysis.report import full_report
    from .analysis.walkforward import walk_forward
    from .engine.backtest import run_backtest
    strategy, cls, cfg, inputs, conf, set_space, workers = _resolve(args)
    space = _space(args, conf, cls, set_space)
    out = _out(args, conf, "results/full")
    ev = _evaluator(strategy, cfg, inputs, workers, out)
    oc, sc, wc = conf.get("optimize") or {}, conf.get("sensitivity") or {}, conf.get("walkforward") or {}
    objective, criteria = _objective(args, conf), _criteria(args, conf)
    print(f"[1/5] optimisation: {len(space.names)} parameters, grid {space.size():,}")
    opt = optimize(ev, space, args.method or oc.get("method", "lhs"), args.n or oc.get("n", 100), objective,
                   criteria, seed=args.seed)
    opt.save(out)
    base = opt.robust_best
    print("[2/5] sensitivity / survival around the robust best")
    sens = S.analyze(ev, space, base, objective, criteria, sc.get("tests", ["oat", "neighborhood", "costs", "periods"]),
                     sc.get("pcts", [5, 10, 20]), sc.get("n_perturb", 40), sc.get("max_points", 9), sc.get("periods", 4))
    sens.save(out)
    wf = None
    if args.walkforward or wc.get("enabled"):
        print("[3/5] walk-forward")
        wf = walk_forward(ev, space, wc.get("is_days", 90), wc.get("oos_days", 30), wc.get("method", "lhs"),
                          wc.get("n", 40), objective, criteria, wc.get("pick", "robust"), wc.get("anchored", False))
        wf.save(out)
    print("[4/5] final backtest of the robust best settings")
    final_cfg = cfg
    if args.final_model:
        final_cfg = type(cfg)(**{**asdict(cfg), "model": args.final_model})
    res = run_backtest(cls, {**inputs, **base}, final_cfg)
    res.save(out / "final_backtest")
    print("[5/5] Monte Carlo")
    mc = monte_carlo(res.trades, cfg.deposit)
    from .mq5 import write_set
    write_set(out / "best_settings.set", {**cls.defaults(), **inputs, **opt.best}, None, cls.mq5_info())
    write_set(out / "robust_best_settings.set", {**cls.defaults(), **inputs, **base}, None, cls.mq5_info())
    with open(out / "summary.json", "w") as f:
        json.dump({"best": opt.best, "robust_best": base, "optimization": opt.summary,
                   "importance": opt.importance, "sensitivity": sens.summary,
                   "walkforward": wf.summary if wf else None, "final_backtest": res.metrics,
                   "montecarlo": mc}, f, indent=2, default=str)
    full_report(out / "report.html", f"{cls.__name__} — full robustness study",
                f"{cfg.symbol} {cfg.timeframe} | {cfg.start} → {cfg.end} | objective {objective}",
                backtest=res, opt=opt, sens=sens, wf=wf, mc=mc)
    _print_json({"best": opt.best, "robust_best": base, "robustness_score": sens.summary.get("robustness_score"),
                 "global_survival_pct": opt.summary["global_survival_profitable_pct"]})
    print(f"-> {out}/report.html, {out}/robust_best_settings.set")


def cmd_mt5test(args):
    from .mt5_tester.runner import MT5TesterConfig, parity, run_tester
    from .mq5 import read_set
    inputs = {}
    if args.set_file:
        inputs.update(read_set(args.set_file)[0])
    for kv in args.param:
        k, v = kv.split("=", 1)
        inputs[k] = _auto_val(v)
    cfg = MT5TesterConfig(terminal=args.terminal, data_dir=args.data_dir, expert=args.expert, symbol=args.symbol,
                          period=args.tf, start=args.start, end=args.end, model=args.model, deposit=args.deposit,
                          leverage=args.leverage)
    res = run_tester(cfg, inputs, mq5=args.mq5, work_dir=args.out or "mt5_runs")
    _print_json(res.get("metrics", {}))
    if args.parity_with:
        import pandas as pd
        py = pd.read_csv(Path(args.parity_with) / "deals.csv")
        _print_json(parity(py, res["deals"]))


def cmd_compile(args):
    from .mt5_tester.runner import compile_ea
    ok = compile_ea(args.metaeditor, args.mq5)
    sys.exit(0 if ok else 1)


def cmd_port(args):
    from .transpile import transpile_file
    out = transpile_file(args.mq5, args.out, args.class_name)
    print(f"draft port written to {out} - review every function marked TODO before trusting results")


# ---------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ubt", description="Universal MT5 EA backtester / optimiser / "
                                 "sensitivity & survival analysis / MT5 data taker")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("inputs", help="list EA inputs from the .mq5; write default .set / auto range file")
    p.add_argument("--mq5", required=True)
    p.add_argument("--write-set")
    p.add_argument("--write-space")
    p.add_argument("--auto-spread", type=float, default=0.5)
    p.add_argument("--auto-points", type=int, default=5)
    p.set_defaults(func=cmd_inputs)

    p = sub.add_parser("download", help="MT5 data taker: asks account/password, saves purified ticks + OHLCV")
    p.add_argument("--mq5", help="take the assets marked in this EA's inputs")
    p.add_argument("--symbols", help="comma list (in addition to --mq5)")
    p.add_argument("--root", default="data")
    p.add_argument("--from", dest="start", help="default: earliest available")
    p.add_argument("--to", dest="end", help="default: now")
    p.add_argument("--timeframes", help="default M1,M5,M15,M30,H1,H2,H4,D1,W1,MN1")
    p.add_argument("--login")
    p.add_argument("--server")
    p.add_argument("--terminal", help="path to terminal64.exe (optional)")
    p.add_argument("--no-ticks", action="store_true")
    p.add_argument("--no-bars", action="store_true")
    p.add_argument("--refresh", action="store_true", help="re-download months already on disk")
    p.add_argument("--chunk-hours", type=int, default=24)
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("synth", help="write synthetic BTC-like data (for trying the tools without MT5)")
    p.add_argument("--root", default="data")
    p.add_argument("--symbol", default="BTCUSD")
    p.add_argument("--from", dest="start", default="2024-01-01")
    p.add_argument("--to", dest="end", default="2024-03-01")
    p.add_argument("--seed", type=int, default=7)
    p.set_defaults(func=cmd_synth)

    p = sub.add_parser("backtest", help="single backtest + HTML report")
    _common(p)
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("optimize", help="grid/random/lhs/genetic optimisation with robust-best + survival")
    _common(p)
    _criteria_args(p)
    _space_args(p)
    p.add_argument("--method", choices=["grid", "random", "lhs", "genetic"])
    p.add_argument("--n", type=int, help="evaluations for random/lhs/genetic")
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(func=cmd_optimize)

    p = sub.add_parser("sensitivity", help="parameter sensitivity + survival %% around a parameter set")
    _common(p)
    _criteria_args(p)
    _space_args(p)
    p.add_argument("--params", help="JSON file/string with the base set (e.g. optimization_summary.json)")
    p.add_argument("--tests", help="comma list: oat,neighborhood,costs,periods")
    p.add_argument("--pcts", help="perturbation %% levels, e.g. 5,10,20")
    p.add_argument("--n-perturb", type=int)
    p.set_defaults(func=cmd_sensitivity)

    p = sub.add_parser("walkforward", help="walk-forward optimisation")
    _common(p)
    _criteria_args(p)
    _space_args(p)
    p.add_argument("--is-days", type=float)
    p.add_argument("--oos-days", type=float)
    p.add_argument("--method", choices=["grid", "random", "lhs", "genetic"])
    p.add_argument("--n", type=int)
    p.add_argument("--anchored", action="store_true")
    p.set_defaults(func=cmd_walkforward)

    p = sub.add_parser("montecarlo", help="Monte Carlo on a trades.csv")
    p.add_argument("--trades", required=True)
    p.add_argument("--deposit", type=float, default=10000)
    p.add_argument("--sims", type=int, default=2000)
    p.add_argument("--ruin-dd", type=float, default=50)
    p.set_defaults(func=cmd_montecarlo)

    p = sub.add_parser("full", help="optimise -> robust best -> sensitivity/survival -> walk-forward -> MC -> report")
    _common(p)
    _criteria_args(p)
    _space_args(p)
    p.add_argument("--method", choices=["grid", "random", "lhs", "genetic"])
    p.add_argument("--n", type=int)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--walkforward", action="store_true")
    p.add_argument("--final-model", choices=["real", "every_tick", "m1_ohlc"],
                   help="tick model for the final confirmation backtest (e.g. real)")
    p.set_defaults(func=cmd_full)

    p = sub.add_parser("mt5test", help="run the ORIGINAL EA in the MT5 Strategy Tester and parse its report")
    p.add_argument("--terminal", required=True)
    p.add_argument("--data-dir", required=True, help="terminal data folder")
    p.add_argument("--expert", required=True, help="path under MQL5\\Experts, e.g. Zscore_and_Levando_MIX.ex5")
    p.add_argument("--mq5", help="source, for input names/defaults")
    p.add_argument("--symbol", default="BTCUSD")
    p.add_argument("--tf", default="M5")
    p.add_argument("--from", dest="start", required=True)
    p.add_argument("--to", dest="end", required=True)
    p.add_argument("--model", default="real", choices=["real", "every_tick", "m1_ohlc", "open_prices"])
    p.add_argument("--deposit", type=float, default=10000)
    p.add_argument("--leverage", type=int, default=100)
    p.add_argument("--set", dest="set_file")
    p.add_argument("--param", action="append", default=[])
    p.add_argument("--out")
    p.add_argument("--parity-with", help="python backtest output folder to compare deals with")
    p.set_defaults(func=cmd_mt5test)

    p = sub.add_parser("compile", help="compile an .mq5 with MetaEditor")
    p.add_argument("--metaeditor", required=True)
    p.add_argument("--mq5", required=True)
    p.set_defaults(func=cmd_compile)

    p = sub.add_parser("port", help="generate a DRAFT Python port of any .mq5 (start of a new strategy)")
    p.add_argument("--mq5", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--class-name")
    p.set_defaults(func=cmd_port)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if not getattr(args, "verbose", False) else logging.DEBUG,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    args.func(args)


if __name__ == "__main__":
    main()
