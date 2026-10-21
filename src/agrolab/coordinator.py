"""Coordinador real: genera la carga, decide con la estrategia y mide.

Un solo hilo con un bucle de eventos: despacha cada lote cuando llega su
instante y, entre lotes, procesa las confirmaciones (DONE) de los
trabajadores. El simulador modela este mismo hilo como un único núcleo de CPU
compartido entre el despacho y la recepción.
"""
import collections
import logging
import time

import zmq

from . import code_hash, protocol, strategies, workload
from .metrics import TaskRecord

try:
    from prometheus_client import Gauge, start_http_server
except ImportError:
    Gauge = start_http_server = None

log = logging.getLogger("agrolab.coordinator")


class RunError(RuntimeError):
    pass


class Coordinator:
    def __init__(self, port: int = 5555, metrics_port: int | None = None):
        self.ctx = zmq.Context.instance()
        self.sock = self.ctx.socket(zmq.ROUTER)
        self.sock.setsockopt(zmq.ROUTER_HANDOVER, 1)
        self.sock.setsockopt(zmq.ROUTER_MANDATORY, 1)
        self.sock.setsockopt(zmq.LINGER, 0)
        self.sock.bind(f"tcp://*:{port}")
        self.code = code_hash()
        self.seen: dict[str, str] = {}  # trabajador -> hash de código (de HELLO/READY)
        self._zero = bytes(0)
        self._metrics = None
        if metrics_port and Gauge is not None:
            start_http_server(metrics_port)
            self._metrics = {
                "active": Gauge("agrolab_run_active", "1 durante una corrida"),
                "strategy": Gauge("agrolab_strategy", "Estrategia en uso", ["strategy"]),
                "outstanding": Gauge("agrolab_outstanding", "Tareas sin confirmar", ["worker"]),
                "dispatched": Gauge("agrolab_run_dispatched", "Despachadas en la corrida", ["worker"]),
                "completed": Gauge("agrolab_run_completed", "Confirmadas en la corrida", ["worker"]),
            }

    # ----------------------------------------------------------------- utilidades
    def _recv(self, timeout_s: float):
        if not self.sock.poll(max(0.0, timeout_s) * 1000):
            return None
        frames = self.sock.recv_multipart()
        who = frames[0].decode()
        msg = protocol.unpack(frames[1])
        if msg["k"] in ("HELLO", "READY"):
            self.seen[who] = msg.get("code", "")
        return who, msg, frames[2:]

    def _send(self, worker: str, header: bytes, *data):
        self.sock.send_multipart([worker.encode(), header, *data], copy=False)

    def wait_for(self, workers: list[str], timeout_s: float = 60.0):
        """Espera el HELLO de todos los trabajadores (arranque del clúster)."""
        deadline = time.monotonic() + timeout_s
        while not set(workers) <= set(self.seen):
            if self._recv(deadline - time.monotonic()) is None and time.monotonic() > deadline:
                missing = sorted(set(workers) - set(self.seen))
                raise RunError(f"no responden: {', '.join(missing)}")

    def _payload(self, size: int):
        if len(self._zero) < size:
            self._zero = bytes(max(size, 2 * len(self._zero)))
        return memoryview(self._zero)[:size]

    # ------------------------------------------------------------- calibración
    def ping(self, worker: str, size: int, reps: int, reply: int = 0) -> list[float]:
        """Tiempos de ida y vuelta (s) de un mensaje de `size` bytes."""
        rtts = []
        for seq in range(reps):
            t0 = time.perf_counter()
            self._send(worker, protocol.pack("PING", seq=seq, reply=reply), self._payload(size))
            while True:
                got = self._recv(10.0)
                if got is None:
                    raise RunError(f"{worker} no respondió el PING")
                who, msg, _ = got
                if who == worker and msg["k"] == "PONG" and msg["seq"] == seq:
                    break
            rtts.append(time.perf_counter() - t0)
        return rtts

    def bench(self, worker: str, units: int, reps: int) -> list[float]:
        self._send(worker, protocol.pack("BENCH", units=units, reps=reps))
        while True:
            got = self._recv(600.0)
            if got is None:
                raise RunError(f"{worker} no terminó la tarea de referencia")
            who, msg, _ = got
            if who == worker and msg["k"] == "BENCH_OK":
                return msg["times"]

    # ------------------------------------------------------------------ corrida
    def run(self, run_id: str, strategy: str, seed: int, spec: workload.Spec,
            workers: list[tuple[str, str, int]], steal: dict, stall_timeout: float = 180.0):
        """Ejecuta una corrida. `workers` = [(nombre, ip, puerto de robo), ...].
        Devuelve (registros por tarea, contadores de mensajes, extras)."""
        names = [w[0] for w in workers]
        n = len(names)
        start = protocol.pack("START", run=run_id, strategy=strategy, seed=seed,
                              peers=[{"name": w, "host": ip, "port": port} for w, ip, port in workers],
                              backoff_min=steal["backoff_min_s"], backoff_max=steal["backoff_max_s"],
                              reply_timeout=steal["reply_timeout_s"])
        for w in names:
            try:
                self._send(w, start)
            except zmq.ZMQError as e:
                raise RunError(f"{w} no está conectado ({e})") from e
        ready = set()
        deadline = time.monotonic() + 15
        while ready != set(names):
            got = self._recv(deadline - time.monotonic())
            if got is None:
                raise RunError(f"sin READY de {sorted(set(names) - ready)}")
            who, msg, _ = got
            if msg["k"] == "READY" and msg["run"] == run_id:
                if msg["code"] != self.code:
                    raise RunError(f"{who} ejecuta otra versión del código ({msg['code']} != {self.code}); "
                                   "volver a aprovisionar: vagrant provision coord")
                ready.add(who)

        tasks = workload.generate(spec, seed)
        strat = strategies.make(strategy, n, seed)
        view = strategies.View(n)
        sent_to = {}
        records = {}
        counters = collections.Counter()
        m = self._metrics
        if m:
            m["active"].set(1)
            for s in strategies.STRATEGIES:
                m["strategy"].labels(strategy=s).set(1 if s == strategy else 0)
            for w in names:
                for g in ("outstanding", "dispatched", "completed"):
                    m[g].labels(worker=w).set(0)

        cpu0 = time.process_time()
        t0 = time.perf_counter()
        nxt = 0
        last_progress = time.monotonic()
        while len(records) < len(tasks):
            now = time.perf_counter() - t0
            while nxt < len(tasks) and tasks[nxt].arrival <= now:
                t = tasks[nxt]
                w = strat.place(t, view)
                view.outstanding[w] += 1
                sent_to[t.tid] = w
                header = protocol.pack("TASK", run=run_id, tid=t.tid, cost=t.cost, kind=t.kind)
                self._send(names[w], header, self._payload(t.size))
                counters["task"] += 1
                if m:
                    m["outstanding"].labels(worker=names[w]).set(view.outstanding[w])
                    m["dispatched"].labels(worker=names[w]).inc()
                nxt += 1
            wait = tasks[nxt].arrival - (time.perf_counter() - t0) if nxt < len(tasks) else 1.0
            got = self._recv(wait)
            if got is None:
                if time.monotonic() - last_progress > stall_timeout:
                    raise RunError(f"corrida {run_id} trabada: {len(records)}/{len(tasks)} confirmadas")
                continue
            who, msg, _ = got
            if msg["k"] != "DONE" or msg["run"] != run_id:
                continue
            done_at = time.perf_counter() - t0
            t = tasks[msg["tid"]]
            w = sent_to[t.tid]
            view.outstanding[w] -= 1
            counters["done"] += 1
            records[t.tid] = TaskRecord(t.tid, t.kind, t.cost, t.arrival, names[w], msg["worker"],
                                        msg["service"], done_at)
            last_progress = time.monotonic()
            if m:
                m["outstanding"].labels(worker=names[w]).set(view.outstanding[w])
                m["completed"].labels(worker=msg["worker"]).inc()
        cpu = time.process_time() - cpu0

        for w in names:
            self._send(w, protocol.pack("END", run=run_id))
        byes = {}
        deadline = time.monotonic() + 15
        while len(byes) < n:
            got = self._recv(deadline - time.monotonic())
            if got is None:
                raise RunError(f"sin BYE de {sorted(set(names) - set(byes))}")
            who, msg, _ = got
            if msg["k"] == "BYE" and msg["run"] == run_id:
                byes[who] = msg
        for b in byes.values():
            counters.update({k: v for k, v in b["counters"].items() if k in ("steal_req", "loot")})
        if m:
            m["active"].set(0)
        extras = {"coord_cpu_s": cpu, "leftover": sum(b["leftover"] for b in byes.values())}
        return [records[i] for i in range(len(tasks))], dict(counters), extras
