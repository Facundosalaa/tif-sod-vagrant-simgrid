"""Métricas de una corrida, calculadas igual para el clúster real y la simulación.

Todos los tiempos se miden con el reloj del coordinador (real) o el reloj de
la simulación, relativos al inicio de la corrida: no se comparan relojes de
máquinas distintas.
"""
import statistics
from dataclasses import dataclass, asdict


@dataclass
class TaskRecord:
    tid: int
    kind: str
    cost: int
    arrival: float      # llegada del lote al coordinador
    sent_to: str        # trabajador elegido por la estrategia
    executed_by: str    # quien la ejecutó (distinto si fue robada)
    service: float      # tiempo de ejecución medido en el trabajador
    done: float         # recepción de la confirmación en el coordinador

    @property
    def response(self) -> float:
        return self.done - self.arrival

    @property
    def wait(self) -> float:
        """Tiempo que la tarea no estuvo ejecutándose: cola + red."""
        return self.response - self.service

    def row(self) -> dict:
        return asdict(self)


def cv(values: list[float]) -> float:
    m = statistics.fmean(values)
    return statistics.pstdev(values) / m if m > 0 else 0.0


def summarize(records: list[TaskRecord], workers: list[str], counters: dict) -> dict:
    makespan = max(r.done for r in records)
    busy = {w: 0.0 for w in workers}
    count = {w: 0 for w in workers}
    for r in records:
        busy[r.executed_by] += r.service
        count[r.executed_by] += 1
    stolen = sum(1 for r in records if r.executed_by != r.sent_to)
    control = counters.get("done", 0) + counters.get("steal_req", 0) + counters.get("loot", 0)
    out = {
        "tasks": len(records),
        "makespan_s": makespan,
        "throughput_tps": len(records) / makespan,
        "mean_wait_s": statistics.fmean(r.wait for r in records),
        "mean_response_s": statistics.fmean(r.response for r in records),
        "cv_busy": cv(list(busy.values())),
        "stolen_tasks": stolen,
        "msgs_task": counters.get("task", 0),
        "msgs_control": control,
        "msgs_steal": counters.get("steal_req", 0) + counters.get("loot", 0),
    }
    for w in workers:
        out[f"busy_{w}"] = busy[w]
        out[f"tasks_{w}"] = count[w]
    return out
