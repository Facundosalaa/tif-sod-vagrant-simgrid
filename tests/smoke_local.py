"""Prueba de humo sin VMs: coordinador y 3 trabajadores en la misma máquina.

  python tests/smoke_local.py

Sirve para verificar el protocolo y las tres estrategias en cualquier
computadora con Python 3.11+ y pyzmq, antes de levantar el clúster.
"""
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agrolab import workload  # noqa: E402
from agrolab.coordinator import Coordinator  # noqa: E402
from agrolab.metrics import summarize  # noqa: E402

TASK_PORT = 15555
WORKERS = [("w1", "127.0.0.1", 15561), ("w2", "127.0.0.1", 15562), ("w3", "127.0.0.1", 15563)]
STEAL = {"backoff_min_s": 0.05, "backoff_max_s": 0.4, "reply_timeout_s": 5.0}
SPEC = workload.Spec(batches=4, tasks_per_batch=9, period_s=0.5, heavy_fraction=0.25, light_cost=800,
                     heavy_cost=8000, light_size=16384, heavy_size=262144, spread=0.5)


def main():
    env = {"PYTHONPATH": str(ROOT / "src"), **__import__("os").environ}
    procs = [subprocess.Popen([sys.executable, "-m", "agrolab", "worker", "--name", name, "--coord", ip,
                               "--task-port", str(TASK_PORT), "--steal-port", str(port), "--metrics-port", "0"],
                              env=env)
             for name, ip, port in WORKERS]
    try:
        coord = Coordinator(TASK_PORT)
        coord.wait_for([w[0] for w in WORKERS], timeout_s=20)
        print("RTT vacío w1:", round(min(coord.ping("w1", 0, 5)) * 1000, 3), "ms")
        for strategy in ("rr", "ll", "ws"):
            records, counters, extras = coord.run(f"smoke-{strategy}-{time.time():.0f}", strategy, 7, SPEC,
                                                  WORKERS, STEAL)
            s = summarize(records, [w[0] for w in WORKERS], counters)
            assert s["tasks"] == SPEC.n_tasks and extras["leftover"] == 0
            print(f"{strategy}: makespan {s['makespan_s']:.2f} s, espera media {s['mean_wait_s']:.3f} s, "
                  f"CV {s['cv_busy']:.3f}, robadas {s['stolen_tasks']}, control {s['msgs_control']}, "
                  f"por nodo {[s['tasks_' + w[0]] for w in WORKERS]}")
        print("OK")
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()
