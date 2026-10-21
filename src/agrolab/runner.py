"""Protocolo experimental en el clúster real.

  agrolab plan   genera experiments/planilla.csv a partir de params.toml
  agrolab run    ejecuta la planilla (se puede cortar y retomar: saltea las
                 corridas que ya están en el CSV de resultados)

Las corridas se agrupan en bloques con las mismas condiciones (latencia y
heterogeneidad) para no reconfigurar la red y la CPU en cada una; dentro de
cada bloque el orden de estrategias y repeticiones es aleatorio (semilla fija)
para no confundir el efecto de la estrategia con derivas del anfitrión.
"""
import csv
import datetime as dt
import json
import os
import pathlib
import random
import statistics
import subprocess
import sys
import time

from . import params as P, workload
from .coordinator import Coordinator
from .metrics import summarize

REPO = P.REPO
PLAN_FIELDS = ["orden", "run_id", "bloque", "latency_ms", "hetero", "strategy", "rep", "seed"]


def make_plan(params: dict) -> list[dict]:
    d = params["design"]
    rng = random.Random(d["order_seed"])
    rows = []
    for lat in d["latencies_ms"]:
        for h in d["hetero"]:
            block = [(s, r) for s in d["strategies"] for r in range(1, d["reps"] + 1)]
            rng.shuffle(block)
            for s, r in block:
                rows.append({
                    "orden": len(rows) + 1,
                    "run_id": f"L{lat}-{h}-{s}-r{r}",
                    "bloque": f"L{lat}-{h}",
                    "latency_ms": lat,
                    "hetero": h,
                    "strategy": s,
                    "rep": r,
                    "seed": d["seed_base"] + r - 1,
                })
    return rows


def write_plan(path: pathlib.Path, rows: list[dict]):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PLAN_FIELDS)
        w.writeheader()
        w.writerows(rows)


def read_csv(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_csv(path: pathlib.Path, rows: list[dict]):
    if not rows:
        return
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if new:
            w.writeheader()
        w.writerows(rows)


def apply_conditions(latency_ms: int, quotas: dict[str, int] | None):
    """Aplica netem y CPUQuota en todos los nodos con Ansible."""
    extra = {"delay_ms": latency_ms}
    if quotas is not None:
        extra["quotas"] = quotas
    prov = REPO / "provisioning"
    env = dict(os.environ, ANSIBLE_CONFIG=str(prov / "ansible.cfg"))
    cmd = ["ansible-playbook", "conditions.yml", "-e", json.dumps(extra)]
    res = subprocess.run(cmd, cwd=prov, env=env, capture_output=True, text=True)
    if res.returncode != 0:
        sys.stderr.write(res.stdout[-3000:] + res.stderr[-3000:])
        raise SystemExit(f"falló conditions.yml con {extra}")


def cluster(params: dict) -> list[tuple[str, str, int]]:
    c = params["cluster"]
    return [(w, ip, c["steal_port"]) for w, ip in zip(c["workers"], c["worker_ips"])]


def measure_rtt(coord: Coordinator, names: list[str]) -> float:
    rtts = []
    for w in names:
        rtts.extend(coord.ping(w, 0, 5))
    return statistics.median(rtts) * 1000


def run_plan(params: dict, plan_path: pathlib.Path, out_dir: pathlib.Path, only: str | None = None):
    rows = read_csv(plan_path)
    if only:
        rows = [r for r in rows if r["run_id"].startswith(only)]
    runs_path = out_dir / "runs.csv"
    tasks_path = out_dir / "tasks.csv"
    done = {r["run_id"] for r in read_csv(runs_path)}
    pending = [r for r in rows if r["run_id"] not in done]
    print(f"{len(rows) - len(pending)} corridas ya hechas, {len(pending)} pendientes", flush=True)
    if not pending:
        return

    workers = cluster(params)
    names = [w[0] for w in workers]
    coord = Coordinator(params["cluster"]["task_port"], params["cluster"].get("metrics_port"))
    coord.wait_for(names)
    spec = workload.Spec.from_params(params)
    current, rtt = None, None
    for i, row in enumerate(pending, 1):
        cond = (int(row["latency_ms"]), row["hetero"])
        if cond != current:
            print(f"== bloque {row['bloque']}: aplicando condiciones", flush=True)
            apply_conditions(cond[0], P.quotas(params, cond[1], names))
            time.sleep(2)
            rtt = measure_rtt(coord, names)
            current = cond
        started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        t0 = time.monotonic()
        records, counters, extras = coord.run(row["run_id"], row["strategy"], int(row["seed"]), spec,
                                              workers, params["stealing"])
        summary = summarize(records, names, counters)
        out = {k: row[k] for k in PLAN_FIELDS}
        out.update({"started": started, "wall_s": round(time.monotonic() - t0, 3),
                    "rtt_ms": round(rtt, 3), "code": coord.code})
        out.update(summary)
        out.update(extras)
        append_csv(runs_path, [out])
        append_csv(tasks_path, [{"run_id": row["run_id"], **r.row()} for r in records])
        print(f"[{i}/{len(pending)}] {row['run_id']}: makespan {summary['makespan_s']:.2f} s, "
              f"espera {summary['mean_wait_s']:.2f} s, CV {summary['cv_busy']:.3f}, "
              f"robadas {summary['stolen_tasks']}", flush=True)
        time.sleep(1)


def main_plan(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="agrolab plan")
    ap.add_argument("--out", default=str(REPO / "experiments" / "planilla.csv"))
    args = ap.parse_args(argv)
    rows = make_plan(P.load())
    write_plan(pathlib.Path(args.out), rows)
    print(f"{len(rows)} corridas -> {args.out}")


def main_run(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="agrolab run")
    ap.add_argument("--plan", default=str(REPO / "experiments" / "planilla.csv"))
    ap.add_argument("--out", default=str(REPO / "experiments" / "results" / "real"))
    ap.add_argument("--only", help="prefijo de run_id (por ejemplo L20-H1)")
    args = ap.parse_args(argv)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    run_plan(P.load(), pathlib.Path(args.plan), out, args.only)
