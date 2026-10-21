"""Núcleo de cómputo de las tareas.

Una unidad de trabajo = SHA-256 sobre un bloque de 32 KiB. Es determinista,
usa un solo núcleo y libera el GIL mientras calcula (hashlib lo hace con
bloques grandes), así que el hilo de comunicaciones del trabajador sigue
atendiendo mensajes mientras se ejecuta una tarea.
"""
import hashlib
import time

BLOCK_BYTES = 32 * 1024
_BLOCK = bytes(BLOCK_BYTES)


def run(units: int) -> str:
    m = hashlib.sha256()
    update = m.update
    for _ in range(units):
        update(_BLOCK)
    return m.hexdigest()[:16]


def bench(units: int, reps: int) -> list[float]:
    """Tiempos (s) de la tarea de referencia, para calibrar la velocidad."""
    times = []
    for _ in range(reps):
        t0 = time.perf_counter()
        run(units)
        times.append(time.perf_counter() - t0)
    return times
