"""Carga de trabajo: lotes que envían las estaciones agrometeorológicas.

Cada período llega un lote con lecturas de sensores (tareas livianas, pocos
datos) e imágenes de cultivo (tareas pesadas, más datos). La generación usa un
random.Random con semilla fija, así que la secuencia es idéntica en el clúster
real y en la simulación.
"""
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    tid: int
    batch: int
    arrival: float  # segundos desde el inicio de la corrida
    cost: int       # unidades de trabajo (bloques del núcleo de cómputo)
    size: int       # bytes de datos que viajan con la tarea
    kind: str       # "lectura" | "imagen"


@dataclass(frozen=True)
class Spec:
    batches: int
    tasks_per_batch: int
    period_s: float
    heavy_fraction: float
    light_cost: int
    heavy_cost: int
    light_size: int
    heavy_size: int
    spread: float

    @classmethod
    def from_params(cls, params: dict, tasks_per_batch: int | None = None) -> "Spec":
        w = params["workload"]
        return cls(
            batches=w["batches"],
            tasks_per_batch=tasks_per_batch or w["tasks_per_batch"],
            period_s=w["period_s"],
            heavy_fraction=w["heavy_fraction"],
            light_cost=w["light_cost"],
            heavy_cost=w["heavy_cost"],
            light_size=w["light_size"],
            heavy_size=w["heavy_size"],
            spread=w["spread"],
        )

    @property
    def n_tasks(self) -> int:
        return self.batches * self.tasks_per_batch

    @property
    def mean_cost(self) -> float:
        return self.heavy_fraction * self.heavy_cost + (1 - self.heavy_fraction) * self.light_cost


def generate(spec: Spec, seed: int) -> list[Task]:
    rng = random.Random(seed)
    tasks = []
    lo, hi = 1 - spec.spread, 1 + spec.spread
    for b in range(spec.batches):
        for _ in range(spec.tasks_per_batch):
            heavy = rng.random() < spec.heavy_fraction
            cost = spec.heavy_cost if heavy else spec.light_cost
            size = spec.heavy_size if heavy else spec.light_size
            tasks.append(Task(
                tid=len(tasks),
                batch=b,
                arrival=round(b * spec.period_s, 6),
                cost=max(1, round(cost * rng.uniform(lo, hi))),
                size=max(1, round(size * rng.uniform(lo, hi))),
                kind="imagen" if heavy else "lectura",
            ))
    return tasks
