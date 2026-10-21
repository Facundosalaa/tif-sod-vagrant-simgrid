"""Trabajador real (servicio systemd agrolab-worker en cada VM).

Dos hilos:
  - comunicaciones: recibe del coordinador (DEALER) y atiende pedidos de robo
    de otros trabajadores (ROUTER); reenvía al coordinador las confirmaciones
    que le pasa el ejecutor;
  - ejecutor: saca tareas de la cola local (FIFO) y las ejecuta. Si la
    estrategia es robo de trabajo y la cola está vacía, roba.

El simulador (agrolab.sim) reproduce esta misma estructura con actores.
"""
import argparse
import collections
import logging
import threading
import time

import zmq

from . import code_hash, kernel, protocol
from .strategies import StealPolicy

try:
    from prometheus_client import Counter, Gauge, start_http_server
except ImportError:  # el trabajador funciona igual sin métricas
    Counter = Gauge = start_http_server = None

log = logging.getLogger("agrolab.worker")


class _Metrics:
    def __init__(self, port: int | None):
        self.enabled = bool(port) and Gauge is not None
        if not self.enabled:
            return
        self.queue = Gauge("agrolab_queue_length", "Tareas en espera en la cola local")
        self.busy = Gauge("agrolab_busy", "1 mientras ejecuta una tarea")
        self.completed = Counter("agrolab_tasks_completed", "Tareas ejecutadas")
        self.busy_seconds = Counter("agrolab_busy_seconds", "Tiempo de CPU dedicado a tareas")
        self.steals = Counter("agrolab_steal_requests", "Pedidos de robo enviados", ["result"])
        start_http_server(port)

    def __getattr__(self, name):  # métricas deshabilitadas: no hacer nada
        return _Noop()


class _Noop:
    def __getattr__(self, name):
        return lambda *a, **k: self

    def labels(self, *a, **k):
        return self


class Worker:
    def __init__(self, name: str, coord: str, task_port: int, steal_port: int, metrics_port: int | None):
        self.name = name
        self.ctx = zmq.Context.instance()
        self.coord = self.ctx.socket(zmq.DEALER)
        self.coord.setsockopt(zmq.IDENTITY, name.encode())
        self.coord.setsockopt(zmq.LINGER, 0)
        self.coord.connect(f"tcp://{coord}:{task_port}")
        self.steal_srv = self.ctx.socket(zmq.ROUTER)
        self.steal_srv.setsockopt(zmq.LINGER, 0)
        self.steal_srv.bind(f"tcp://*:{steal_port}")
        self.events = self.ctx.socket(zmq.PAIR)
        self.events.bind(f"inproc://events-{name}")

        self.cv = threading.Condition()
        self.queue = collections.deque()  # (encabezado, datos)
        self.run = None                    # parámetros de la corrida en curso
        self.epoch = 0                     # cambia con cada START/END
        self.counters = collections.Counter()
        self.m = _Metrics(metrics_port)
        self.code = code_hash()

        threading.Thread(target=self._executor, name="ejecutor", daemon=True).start()

    # ------------------------------------------------------------ comunicaciones
    def serve_forever(self):
        poller = zmq.Poller()
        for s in (self.coord, self.steal_srv, self.events):
            poller.register(s, zmq.POLLIN)
        last_hello = 0.0
        while True:
            if self.run is None and time.monotonic() - last_hello > 5:
                self.coord.send(protocol.pack("HELLO", worker=self.name, code=self.code))
                last_hello = time.monotonic()
            socks = dict(poller.poll(1000))
            if self.coord in socks:
                self._on_coord(self.coord.recv_multipart(copy=False))
            if self.steal_srv in socks:
                self._on_steal(self.steal_srv.recv_multipart())
            if self.events in socks:
                self.coord.send(self.events.recv())

    def _on_coord(self, frames):
        msg = protocol.unpack(frames[0].bytes)
        kind = msg["k"]
        if kind == "TASK":
            with self.cv:
                if self.run is not None and msg["run"] == self.run["run"]:
                    self.queue.append((msg, frames[1]))
                    self.m.queue.set(len(self.queue))
                    self.cv.notify()
        elif kind == "START":
            with self.cv:
                self.queue.clear()
                self.run = msg
                self.epoch += 1
                self.counters = collections.Counter()
                self.cv.notify_all()
            self.coord.send(protocol.pack("READY", run=msg["run"], worker=self.name, code=self.code))
        elif kind == "END":
            with self.cv:
                leftover = len(self.queue)
                self.queue.clear()
                self.run = None
                self.epoch += 1
                counters = dict(self.counters)
                self.cv.notify_all()
            self.m.queue.set(0)
            self.coord.send(protocol.pack("BYE", run=msg["run"], worker=self.name,
                                          counters=counters, leftover=leftover))
        elif kind == "PING":
            self.coord.send_multipart([protocol.pack("PONG", seq=msg["seq"]), bytes(msg.get("reply", 0))])
        elif kind == "BENCH":
            times = kernel.bench(msg["units"], msg["reps"])
            self.coord.send(protocol.pack("BENCH_OK", worker=self.name, units=msg["units"], times=times))

    def _on_steal(self, frames):
        ident, header = frames[0], frames[1]
        msg = protocol.unpack(header)
        with self.cv:
            items = []
            if self.run is not None and msg["run"] == self.run["run"]:
                k = StealPolicy.amount(len(self.queue))
                items = [self.queue.pop() for _ in range(k)]
                items.reverse()
                self.m.queue.set(len(self.queue))
            self.counters["loot"] += 1
            self.counters["given"] += len(items)
        reply = [ident, protocol.pack("LOOT", run=msg["run"], req=msg["req"], tasks=[h for h, _ in items])]
        reply.extend(p for _, p in items)
        self.steal_srv.send_multipart(reply)

    # ------------------------------------------------------------------ ejecutor
    def _executor(self):
        events = self.ctx.socket(zmq.PAIR)
        events.connect(f"inproc://events-{self.name}")
        peers, policy, my_epoch = [], None, None
        failures, next_steal, req = 0, 0.0, 0
        while True:
            task = run = None
            with self.cv:
                while True:
                    run = self.run
                    if self.epoch != my_epoch:
                        break
                    if self.queue:
                        task = self.queue.popleft()
                        self.m.queue.set(len(self.queue))
                        break
                    if run is not None and run["strategy"] == "ws":
                        wait = next_steal - time.monotonic()
                        if wait <= 0:
                            break
                        self.cv.wait(wait)
                    else:
                        self.cv.wait()
                epoch = self.epoch

            if epoch != my_epoch:  # empezó o terminó una corrida
                for s in peers:
                    s.close(0)
                peers, policy = [], None
                failures, next_steal = 0, 0.0
                if run is not None and run["strategy"] == "ws":
                    names = [p["name"] for p in run["peers"]]
                    me = names.index(self.name)
                    for p in run["peers"]:
                        s = self.ctx.socket(zmq.DEALER)
                        s.setsockopt(zmq.LINGER, 0)
                        if p["name"] != self.name:
                            s.connect(f"tcp://{p['host']}:{p['port']}")
                        peers.append(s)
                    policy = StealPolicy(me, len(names), run["seed"], run["backoff_min"], run["backoff_max"])
                my_epoch = epoch
                continue

            if task is not None:
                header, payload = task
                self.m.busy.set(1)
                t0 = time.perf_counter()
                kernel.run(header["cost"])
                service = time.perf_counter() - t0
                self.m.busy.set(0)
                self.m.completed.inc()
                self.m.busy_seconds.inc(service)
                with self.cv:
                    qlen = len(self.queue)
                events.send(protocol.pack("DONE", run=header["run"], tid=header["tid"], worker=self.name,
                                          service=service, stolen=header.get("stolen", False), qlen=qlen))
                failures, next_steal = 0, 0.0
                continue

            # cola vacía con robo de trabajo: pedirle a una víctima al azar
            req += 1
            got = self._steal(peers[policy.choose_victim()], run, req)
            if got:
                failures, next_steal = 0, 0.0
            else:
                failures += 1
                next_steal = time.monotonic() + policy.backoff(failures)

    def _steal(self, sock, run, req) -> int:
        sock.send(protocol.pack("STEAL", run=run["run"], req=req, thief=self.name))
        with self.cv:
            self.counters["steal_req"] += 1
        deadline = time.monotonic() + run["reply_timeout"]
        while (left := deadline - time.monotonic()) > 0:
            if not sock.poll(left * 1000):
                break
            frames = sock.recv_multipart()
            msg = protocol.unpack(frames[0])
            if msg["req"] != req:
                continue  # respuesta vieja que llegó tarde
            items = []
            for h, payload in zip(msg["tasks"], frames[1:]):
                h["stolen"] = True
                items.append((h, payload))
            with self.cv:
                if self.run is not None and self.run["run"] == run["run"]:
                    self.queue.extend(items)
                    self.m.queue.set(len(self.queue))
                    self.counters["stolen"] += len(items)
                else:
                    items = []
            self.m.steals.labels(result="ok" if items else "vacio").inc()
            return len(items)
        self.m.steals.labels(result="sin_respuesta").inc()
        return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="agrolab worker", description="Trabajador AgroLab")
    ap.add_argument("--name", required=True)
    ap.add_argument("--coord", required=True, help="dirección IP del coordinador")
    ap.add_argument("--task-port", type=int, default=5555)
    ap.add_argument("--steal-port", type=int, default=5556)
    ap.add_argument("--metrics-port", type=int, default=8000, help="0 = sin métricas Prometheus")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    log.info("trabajador %s, código %s, coordinador %s", args.name, code_hash(), args.coord)
    Worker(args.name, args.coord, args.task_port, args.steal_port, args.metrics_port or None).serve_forever()


if __name__ == "__main__":
    main()
