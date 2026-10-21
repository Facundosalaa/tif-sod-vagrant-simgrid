"""Simulación con SimGrid (interfaz S4U de Python) del mismo sistema.

  agrolab simulate trivial      una tarea y un nodo, contra el cálculo manual
  agrolab simulate validate     las configuraciones del clúster real
  agrolab simulate scale        extrapolación a cientos de nodos

Estructura de actores, calcada del sistema real:
  coordinador: "despacho" (llegada de lotes + estrategia) y "recepción" (DONE)
               comparten un único núcleo, como el hilo único del coordinador;
  trabajador:  "buzón" (recibe tareas), "ejecutor" (cola FIFO, roba si la
               estrategia lo pide) y "servidor de robo" (atiende a ladrones).

Las decisiones las toma agrolab.strategies y la carga la genera
agrolab.workload: los mismos módulos que usa el clúster real.
"""
import collections
import concurrent.futures as cf
import csv
import json
import multiprocessing as mp
import os
import pathlib
import tempfile
import time

from . import params as P, platform as plat, protocol, strategies, workload
from .metrics import TaskRecord, summarize

HDR = protocol.HEADER_BYTES
TASK_META = 80  # bytes por tarea dentro de una respuesta de robo
SIM_ARGS = ["--cfg=network/model:CM02", "--cfg=network/crosstraffic:0", "--log=root.thres:critical"]
CAL_PATH = P.REPO / "experiments" / "calibration" / "calibration.json"
OUT = P.REPO / "experiments" / "results" / "sim"


def simulate(job: dict) -> dict:
    """Ejecuta una simulación. Debe correr en un proceso propio (SimGrid admite
    un solo Engine por proceso)."""
    from simgrid import Actor, Engine, Host, Mailbox, Semaphore, this_actor

    wall0 = time.perf_counter()
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as f:
        f.write(job["xml"])
        xml_path = f.name
    e = Engine(["agrolab-sim", *SIM_ARGS])
    e.load_platform(xml_path)

    spec = workload.Spec(**job["spec"])
    tasks = workload.generate(spec, job["seed"])
    n = job["n_workers"]
    names = [f"w{i + 1}" for i in range(n)]
    strat = strategies.make(job["strategy"], n, job["seed"])
    view = strategies.View(n)
    coord_speed = Host.by_name("coord").speed
    c_msg = job["coord_msg_cost_s"] * coord_speed
    c_dispatch = c_msg + job["ll_per_worker_s"] * coord_speed * max(0, strat.decision_ops() - 1)
    st = job["stealing"]

    queues = [collections.deque() for _ in range(n)]
    waiting = [False] * n
    sems = [Semaphore(0) for _ in range(n)]
    sent_to = {}
    records = {}
    counters = collections.Counter()

    def dispatcher():
        for t in tasks:
            if Engine.clock < t.arrival:
                this_actor.sleep_until(t.arrival)
            this_actor.execute(c_dispatch)
            w = strat.place(t, view)
            view.outstanding[w] += 1
            sent_to[t.tid] = w
            Mailbox.by_name(f"in-{w}").put_init(t, HDR + t.size).detach()
            counters["task"] += 1

    def collector():
        mb = Mailbox.by_name("coord")
        mb.set_receiver(Actor.self())
        while len(records) < len(tasks):
            tid, ex, service = mb.get()
            done_at = Engine.clock
            this_actor.execute(c_msg)
            t = tasks[tid]
            w = sent_to[tid]
            view.outstanding[w] -= 1
            counters["done"] += 1
            records[tid] = TaskRecord(tid, t.kind, t.cost, t.arrival, names[w], names[ex], service, done_at)

    def inbox(i):
        mb = Mailbox.by_name(f"in-{i}")
        mb.set_receiver(Actor.self())
        while True:
            t = mb.get()
            queues[i].append(t)
            if waiting[i]:
                waiting[i] = False
                sems[i].release()

    def steal_server(i):
        mb = Mailbox.by_name(f"steal-{i}")
        mb.set_receiver(Actor.self())
        while True:
            thief = mb.get()
            q = queues[i]
            items = [q.pop() for _ in range(strategies.StealPolicy.amount(len(q)))]
            items.reverse()
            counters["loot"] += 1
            size = HDR + sum(TASK_META + t.size for t in items)
            Mailbox.by_name(f"loot-{thief}").put_init(items, size).detach()

    def executor(i):
        policy = strategies.StealPolicy(i, n, job["seed"], st["backoff_min_s"], st["backoff_max_s"])
        loot = Mailbox.by_name(f"loot-{i}")
        loot.set_receiver(Actor.self())
        coord_mb = Mailbox.by_name("coord")
        failures, next_steal = 0, 0.0
        while True:
            if queues[i]:
                t = queues[i].popleft()
                t0 = Engine.clock
                this_actor.execute(t.cost)
                coord_mb.put_init((t.tid, i, Engine.clock - t0), HDR).detach()
                failures, next_steal = 0, 0.0
                continue
            if strat.steals:
                now = Engine.clock
                if now >= next_steal:
                    counters["steal_req"] += 1
                    Mailbox.by_name(f"steal-{policy.choose_victim()}").put_init(i, HDR).detach()
                    items = loot.get()
                    if items:
                        queues[i].extend(items)
                        failures, next_steal = 0, 0.0
                    else:
                        failures += 1
                        next_steal = Engine.clock + policy.backoff(failures)
                    continue
                waiting[i] = True
                sems[i].acquire_timeout(next_steal - now)
                waiting[i] = False
            else:
                waiting[i] = True
                sems[i].acquire()
                waiting[i] = False

    coord = Host.by_name("coord")
    Actor.create("despacho", coord, dispatcher).daemonize()
    Actor.create("recepcion", coord, collector)
    for i, w in enumerate(names):
        h = Host.by_name(w)
        Actor.create(f"buzon-{w}", h, inbox, i).daemonize()
        Actor.create(f"robo-{w}", h, steal_server, i).daemonize()
        Actor.create(f"ejecutor-{w}", h, executor, i).daemonize()
    e.run()
    os.unlink(xml_path)

    recs = [records[i] for i in range(len(tasks))]
    out = summarize(recs, names, counters) if n <= 3 else summarize_large(recs, names, counters)
    coord_busy = (counters["task"] * c_dispatch + counters["done"] * c_msg) / coord_speed
    out["coord_util"] = coord_busy / out["makespan_s"]
    out["sim_wall_s"] = time.perf_counter() - wall0
    if job.get("keep_tasks"):
        out["_tasks"] = [r.row() for r in recs]
    return out


def summarize_large(records, names, counters):
    """Como summarize, sin las columnas por trabajador (con cientos de nodos)."""
    full = summarize(records, names, counters)
    return {k: v for k, v in full.items() if not k.startswith(("busy_w", "tasks_w"))}


# ---------------------------------------------------------------------- trabajos
def load_cal() -> dict:
    return json.loads(CAL_PATH.read_text(encoding="utf-8"))


def make_job(params, cal, strategy, seed, level, latency_ms, n_workers, tasks_per_batch=None):
    spec = workload.Spec.from_params(params, tasks_per_batch)
    xml, info = plat.from_calibration(cal, level, latency_ms, n_workers)
    return {
        "strategy": strategy, "seed": seed, "hetero": level, "latency_ms": latency_ms,
        "n_workers": n_workers, "tasks_per_batch": spec.tasks_per_batch,
        "spec": spec.__dict__, "xml": xml, "platform": info,
        "coord_msg_cost_s": cal["coord_msg_cost_s"], "ll_per_worker_s": cal["ll_decision"]["per_worker_s"],
        "stealing": params["stealing"],
    }


def _run_job(job):
    res = simulate(job)
    keys = ("strategy", "seed", "hetero", "latency_ms", "n_workers", "tasks_per_batch")
    return {**{k: job[k] for k in keys}, **res}


def run_jobs(jobs, out_csv: pathlib.Path, procs: int, tasks_csv: pathlib.Path | None = None):
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    rows, task_rows = [], []
    t0 = time.perf_counter()
    # Un proceso nuevo por simulación (SimGrid admite un solo Engine por proceso).
    with cf.ProcessPoolExecutor(procs, mp_context=mp.get_context("spawn"), max_tasks_per_child=1) as pool:
        for k, row in enumerate(pool.map(_run_job, jobs), 1):
            tasks = row.pop("_tasks", None)
            if tasks is not None:
                rid = f"L{row['latency_ms']}-{row['hetero']}-{row['strategy']}-s{row['seed']}"
                task_rows += [{"sim_id": rid, **t} for t in tasks]
            rows.append(row)
            print(f"[{k}/{len(jobs)}] N={row['n_workers']} L{row['latency_ms']} {row['hetero']} "
                  f"{row['strategy']} s{row['seed']}: makespan {row['makespan_s']:.2f} s "
                  f"(sim {row['sim_wall_s']:.1f} s)", flush=True)
    write_csv(out_csv, rows)
    if tasks_csv is not None:
        write_csv(tasks_csv, task_rows)
    print(f"{len(rows)} simulaciones en {time.perf_counter() - t0:.0f} s -> {out_csv}")


def write_csv(path, rows):
    fields = []
    for r in rows:
        fields += [k for k in r if k not in fields]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------------- comandos
def trivial(cal):
    """Paso 4: una tarea y un trabajador, comparado con la cuenta a mano."""
    params = P.load()
    lat_ms = params["design"]["latencies_ms"][-1]
    speed = 50_000.0
    cost, size = 25_000, 262_144
    _, info = plat.from_calibration(cal, "H1", lat_ms, 1)
    L, B, Bw = info["latency_s"], info["bandwidth_Bps"], info["worker_bw_Bps"]
    xml = plat.build_xml(cal["coord_speed"], [speed], L, B, Bw)
    spec = {"batches": 1, "tasks_per_batch": 1, "period_s": 1.0, "heavy_fraction": 1.0, "light_cost": cost,
            "heavy_cost": cost, "light_size": size, "heavy_size": size, "spread": 0.0}
    job = {"strategy": "rr", "seed": 1, "n_workers": 1, "spec": spec, "xml": xml,
           "coord_msg_cost_s": cal["coord_msg_cost_s"], "ll_per_worker_s": 0.0, "stealing": params["stealing"]}
    with cf.ProcessPoolExecutor(1, mp_context=mp.get_context("spawn"), max_tasks_per_child=1) as pool:
        res = pool.submit(simulate, job).result()
    c = cal["coord_msg_cost_s"]
    rate = min(B, Bw)  # la ruta atraviesa el enlace del coordinador y el del trabajador
    manual = {
        "despacho en el coordinador": c,
        "envío de la tarea: L + (encabezado + datos) / min(B, Bw)": L + (HDR + size) / rate,
        "ejecución: costo / velocidad": cost / speed,
        "confirmación: L + encabezado / min(B, Bw)": L + HDR / rate,
    }
    total = sum(manual.values())
    print(f"Plataforma: L = {L * 1000:.3f} ms, B coordinador = {B / 1e6:.1f} MB/s, "
          f"B trabajador = {Bw / 1e6:.3f} MB/s (ventana {info['tcp_window_B'] / 1024:.1f} KiB), "
          f"trabajador a {speed:.0f} u/s")
    for k, v in manual.items():
        print(f"  {k:<62} {v * 1000:10.3f} ms")
    print(f"  {'total calculado a mano':<62} {total * 1000:10.3f} ms")
    print(f"  {'total simulado (makespan)':<62} {res['makespan_s'] * 1000:10.3f} ms")
    print(f"  diferencia relativa: {abs(res['makespan_s'] - total) / total:.2e}")


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="agrolab simulate")
    ap.add_argument("mode", choices=["trivial", "one", "validate", "scale"])
    ap.add_argument("--procs", type=int, default=max(1, (os.cpu_count() or 2) - 0))
    ap.add_argument("--nodes", type=int, nargs="*", help="solo estos N (modo scale)")
    ap.add_argument("--latencies", type=int, nargs="*", help="solo estas latencias (modo scale)")
    ap.add_argument("--levels", nargs="*", help="solo estos niveles de heterogeneidad (modo scale)")
    ap.add_argument("--seeds", type=int, nargs="*", help="solo estas semillas (modo scale)")
    ap.add_argument("--tag", default="", help="sufijo del CSV de salida (modo scale)")
    ap.add_argument("--strategy", default="ws", help="modo one")
    ap.add_argument("--hetero", default="H1", help="modo one")
    ap.add_argument("--latency", type=int, default=20, help="modo one")
    ap.add_argument("--seed", type=int, default=1000, help="modo one")
    ap.add_argument("--workers", type=int, default=3, help="modo one")
    args = ap.parse_args(argv)
    params = P.load()
    cal = load_cal()
    d = params["design"]
    if args.mode == "trivial":
        trivial(cal)
        return
    if args.mode == "one":
        base = params["workload"]["tasks_per_batch"] / len(params["cluster"]["workers"])
        job = make_job(params, cal, args.strategy, args.seed, args.hetero, args.latency, args.workers,
                       max(1, round(base * args.workers)))
        with cf.ProcessPoolExecutor(1, mp_context=mp.get_context("spawn"), max_tasks_per_child=1) as pool:
            res = pool.submit(simulate, job).result()
        print(f"Simulación {args.strategy} {args.hetero} L{args.latency} semilla {args.seed}, "
              f"{args.workers} trabajadores:")
        for k in ("makespan_s", "throughput_tps", "mean_wait_s", "cv_busy", "stolen_tasks", "msgs_control",
                  "coord_util", "sim_wall_s"):
            print(f"  {k:<16} {res[k]:.3f}" if isinstance(res[k], float) else f"  {k:<16} {res[k]}")
        return
    if args.mode == "validate":
        seeds = [d["seed_base"] + r for r in range(d["reps"])]
        jobs = [dict(make_job(params, cal, s, seed, h, lat, len(params["cluster"]["workers"])), keep_tasks=True)
                for lat in d["latencies_ms"] for h in d["hetero"] for s in d["strategies"] for seed in seeds]
        run_jobs(jobs, OUT / "validation.csv", args.procs, OUT / "validation_tasks.csv")
        return
    sc = params["scale"]
    base = params["workload"]["tasks_per_batch"] / len(params["cluster"]["workers"])
    nodes = args.nodes or sc["nodes"]
    lats = args.latencies or d["latencies_ms"]
    levels = args.levels or d["hetero"]
    seeds = args.seeds or sc["seeds"]
    jobs = [make_job(params, cal, s, seed, h, lat, n, max(1, round(base * n)))
            for n in nodes for lat in lats for h in levels for s in d["strategies"] for seed in seeds]
    jobs.sort(key=lambda j: -j["n_workers"])  # los grandes primero, para repartir mejor
    run_jobs(jobs, OUT / f"scale{args.tag}.csv", args.procs)
