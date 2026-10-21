"""Estrategias de planificación y balanceo de carga (módulo común).

Siguiendo la clasificación de Shivaratri, Krueger y Singhal (1992):

  rr  Round Robin estático. Centralizada, sin información de estado: la tarea
      i va al trabajador i mod N.
  ll  Menos cargado. Centralizada y dinámica: el coordinador lleva la cuenta de
      tareas despachadas y no confirmadas de cada trabajador y elige la menor.
  ws  Robo de trabajo (Blumofe y Leiserson, 1999). Distribuida y dinámica,
      iniciada por el receptor: el coordinador reparte como Round Robin y cada
      trabajador que se queda sin cola le pide la mitad de la suya a una
      víctima elegida al azar.

Ni el coordinador real ni el simulador toman decisiones por su cuenta: llaman
a estas clases.
"""
import random


class View:
    """Lo que el coordinador sabe de los trabajadores."""

    def __init__(self, n: int):
        self.n = n
        self.outstanding = [0] * n  # despachadas y todavía sin confirmar


class Strategy:
    name = ""
    label = ""
    steals = False  # True si los trabajadores roban trabajo entre sí

    def __init__(self, n: int, seed: int):
        self.n = n
        self.seed = seed

    def place(self, task, view: View) -> int:
        """Índice del trabajador que recibe una tarea nueva."""
        raise NotImplementedError

    def decision_ops(self) -> int:
        """Trabajadores que examina cada decisión (costo de CPU en el
        coordinador, lo usa el simulador)."""
        return 1


class RoundRobin(Strategy):
    name = "rr"
    label = "Round Robin estático"

    def __init__(self, n, seed):
        super().__init__(n, seed)
        self._next = 0

    def place(self, task, view):
        w = self._next
        self._next = (w + 1) % self.n
        return w


class LeastLoaded(Strategy):
    name = "ll"
    label = "Menos cargado (centralizado)"

    def __init__(self, n, seed):
        super().__init__(n, seed)
        self._start = 0  # los empates se resuelven en forma rotativa

    def place(self, task, view):
        best, best_load = -1, None
        for k in range(self.n):
            w = (self._start + k) % self.n
            load = view.outstanding[w]
            if best_load is None or load < best_load:
                best, best_load = w, load
        self._start = (best + 1) % self.n
        return best

    def decision_ops(self):
        return self.n


class WorkStealing(RoundRobin):
    name = "ws"
    label = "Robo de trabajo"
    steals = True


STRATEGIES = {s.name: s for s in (RoundRobin, LeastLoaded, WorkStealing)}


def make(name: str, n: int, seed: int) -> Strategy:
    return STRATEGIES[name](n, seed)


class StealPolicy:
    """Lado del ladrón en el robo de trabajo (corre en cada trabajador).

    - Política de transferencia: robar cuando la cola local queda vacía.
    - Política de ubicación: víctima uniforme al azar entre los demás.
    - Política de selección: la mitad (redondeando hacia arriba) de las tareas
      en espera de la víctima, tomadas del final de su cola.
    - Si el robo falla, se espera un tiempo que crece en forma exponencial
      (backoff) antes de volver a intentar.
    """

    def __init__(self, me: int, n: int, seed: int, backoff_min: float, backoff_max: float):
        self.me = me
        self.n = n
        self.rng = random.Random(seed * 7919 + me)
        self.backoff_min = backoff_min
        self.backoff_max = backoff_max

    def choose_victim(self) -> int:
        v = self.rng.randrange(self.n - 1)
        return v if v < self.me else v + 1

    @staticmethod
    def amount(queued: int) -> int:
        return (queued + 1) // 2

    def backoff(self, failures: int) -> float:
        return min(self.backoff_max, self.backoff_min * 2 ** (failures - 1))
