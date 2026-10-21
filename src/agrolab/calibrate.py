"""Calibración del modelo de simulación con mediciones del clúster real.

  agrolab calibrate        mide y escribe experiments/calibration/calibration.json

Qué mide (paso 6 de la consigna):
  1. Velocidad de cada trabajador (unidades/s) con la tarea de referencia, en
     cada nivel de heterogeneidad, y la del coordinador.
  2. Red: tiempo de ida de mensajes de distintos tamaños en cada nivel de
     latencia; se ajusta t(S) = L + S / B por mínimos cuadrados.
  3. Costo de CPU del coordinador por mensaje, con una corrida de calibración
     (semilla que no se usa en el diseño experimental).
  4. Costo de una decisión de Menos cargado en función de N (microbenchmark del
     mismo código de agrolab.strategies).
"""
import json
import pathlib
import platform as pyplatform
import statistics
import time

from . import kernel, params as P, strategies, workload
from .coordinator import Coordinator
from .runner import apply_conditions, cluster, append_csv

OUT = P.REPO / "experiments" / "calibration"


def linfit(xs, ys):
    """Mínimos cuadrados y = a + b x. Devuelve (a, b, r2)."""
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    ss_res = sum((y - a - b * x) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - my) ** 2 for y in ys)
    return a, b, 1 - ss_res / ss_tot if ss_tot else 1.0


def ll_decision_cost(ns=(3, 16, 64, 256, 512, 1024), calls=3000):
    rows = []
    for n in ns:
        s = strategies.make("ll", n, 0)
        v = strategies.View(n)
        t0 = time.perf_counter()
        for i in range(calls):
            w = s.place(None, v)
            v.outstanding[w] += 1
        rows.append({"n": n, "s_per_decision": (time.perf_counter() - t0) / calls})
    a, b, r2 = linfit([r["n"] for r in rows], [r["s_per_decision"] for r in rows])
    return rows, {"base_s": a, "per_worker_s": b, "r2": r2}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="agrolab calibrate")
    ap.add_argument("--skip-network", action="store_true")
    args = ap.parse_args(argv)
    params = P.load()
    cal = params["calibration"]
    workers = cluster(params)
    names = [w[0] for w in workers]
    OUT.mkdir(parents=True, exist_ok=True)
    result = {"measured_at": time.strftime("%Y-%m-%d %H:%M:%S"), "python": pyplatform.python_version(),
              "kernel_block_bytes": kernel.BLOCK_BYTES, "ref_units": cal["ref_units"]}

    coord = Coordinator(params["cluster"]["task_port"])
    coord.wait_for(names)

    # 1. CPU ------------------------------------------------------------------
    print("== CPU del coordinador", flush=True)
    times = kernel.bench(cal["ref_units"], cal["bench_reps"])
    result["coord_speed"] = cal["ref_units"] / statistics.median(times)
    cpu_rows = [{"node": "coord", "level": "-", "quota": 100, "rep": i, "seconds": t} for i, t in enumerate(times)]
    result["worker_speed"] = {}
    levels = {"REF": [100] * 3, **params["hetero"]}
    for level, pattern in levels.items():
        quotas = {w: pattern[i % len(pattern)] for i, w in enumerate(names)}
        print(f"== CPU de los trabajadores, nivel {level} {quotas}", flush=True)
        apply_conditions(1, quotas)
        time.sleep(1)
        speeds = {}
        for w in names:
            times = coord.bench(w, cal["ref_units"], cal["bench_reps"])
            speeds[w] = cal["ref_units"] / statistics.median(times)
            cpu_rows += [{"node": w, "level": level, "quota": quotas[w], "rep": i, "seconds": t}
                         for i, t in enumerate(times)]
            print(f"   {w}: {speeds[w]:.0f} u/s (mediana de {len(times)})", flush=True)
        result["worker_speed"][level] = speeds
    (OUT / "cpu.csv").unlink(missing_ok=True)
    append_csv(OUT / "cpu.csv", cpu_rows)

    # 2. Red ------------------------------------------------------------------
    if not args.skip_network:
        result["network"] = {}
        net_rows = []
        for lat in [0] + params["design"]["latencies_ms"]:
            apply_conditions(lat, None)
            time.sleep(1)
            print(f"== Red con netem {lat} ms", flush=True)
            xs, ys = [], []
            for w in names:
                med = {}
                for size in cal["ping_sizes"]:
                    rtts = []
                    for _ in range(cal["ping_reps"]):
                        time.sleep(cal["ping_idle_s"])  # conexión "en frío", como entre lotes
                        rtts.extend(coord.ping(w, size, 1))
                    med[size] = statistics.median(rtts)
                    net_rows += [{"netem_ms": lat, "worker": w, "size": size, "rtt_s": r} for r in rtts]
                base = med[0] / 2  # ida de un mensaje vacío
                for size in cal["ping_sizes"]:
                    xs.append(size)
                    ys.append(med[size] - base)  # ida del mensaje de `size` bytes
            a, b, r2 = linfit(xs, ys)
            result["network"][str(lat)] = {"latency_s": a, "bandwidth_Bps": 1 / b, "r2": r2}
            print(f"   L = {a * 1000:.2f} ms, B = {8 / b / 1e6:.0f} Mbit/s, r2 = {r2:.3f}", flush=True)
        (OUT / "network.csv").unlink(missing_ok=True)
        append_csv(OUT / "network.csv", net_rows)

    # 3. Costo del coordinador por mensaje -------------------------------------
    print("== Corrida de calibración del coordinador", flush=True)
    apply_conditions(1, P.quotas(params, "H0", names))
    time.sleep(1)
    spec = workload.Spec.from_params(params)
    msg_costs = []
    for strat in ("rr", "ll", "ws"):
        records, counters, extras = coord.run(f"CAL-{strat}", strat, cal["seed"], spec, workers, params["stealing"])
        msgs = counters.get("task", 0) + counters.get("done", 0)
        msg_costs.append(extras["coord_cpu_s"] / msgs)
        print(f"   {strat}: {extras['coord_cpu_s']:.3f} s de CPU para {msgs} mensajes", flush=True)
    result["coord_msg_cost_s"] = statistics.median(msg_costs)

    # 4. Decisión de Menos cargado -------------------------------------------
    rows, fit = ll_decision_cost()
    result["ll_decision"] = fit
    (OUT / "ll_decision.csv").unlink(missing_ok=True)
    append_csv(OUT / "ll_decision.csv", rows)

    apply_conditions(1, P.quotas(params, "H0", names))
    (OUT / "calibration.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
