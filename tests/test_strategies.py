"""Pruebas del módulo común (python -m pytest tests  o  python tests/test_strategies.py)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from agrolab import strategies, workload  # noqa: E402

SPEC = workload.Spec(batches=12, tasks_per_batch=8, period_s=3.0, heavy_fraction=0.25, light_cost=8000,
                     heavy_cost=64000, light_size=16384, heavy_size=262144, spread=0.5)


def test_workload_es_determinista():
    assert workload.generate(SPEC, 1000) == workload.generate(SPEC, 1000)
    assert workload.generate(SPEC, 1000) != workload.generate(SPEC, 1001)


def test_workload_respeta_los_parametros():
    tasks = workload.generate(SPEC, 1000)
    assert len(tasks) == 96
    assert [t.tid for t in tasks] == list(range(96))
    assert {t.arrival for t in tasks} == {b * 3.0 for b in range(12)}
    for t in tasks:
        mean = SPEC.heavy_cost if t.kind == "imagen" else SPEC.light_cost
        assert 0.5 * mean <= t.cost <= 1.5 * mean


def test_round_robin_cicla():
    s, v = strategies.make("rr", 3, 0), strategies.View(3)
    assert [s.place(None, v) for _ in range(7)] == [0, 1, 2, 0, 1, 2, 0]


def test_menos_cargado_elige_el_minimo():
    s, v = strategies.make("ll", 3, 0), strategies.View(3)
    v.outstanding = [4, 1, 3]
    assert s.place(None, v) == 1
    v.outstanding = [2, 2, 2]  # empate: rota a partir del último elegido
    assert s.place(None, v) == 2
    assert s.decision_ops() == 3


def test_robo_reparte_como_round_robin():
    s, v = strategies.make("ws", 3, 0), strategies.View(3)
    assert s.steals and [s.place(None, v) for _ in range(4)] == [0, 1, 2, 0]


def test_victima_nunca_es_el_propio_ladron():
    for me in range(4):
        p = strategies.StealPolicy(me, 4, 1000, 0.05, 0.4)
        victims = {p.choose_victim() for _ in range(200)}
        assert me not in victims and victims == set(range(4)) - {me}


def test_politica_de_seleccion_y_backoff():
    assert [strategies.StealPolicy.amount(q) for q in range(6)] == [0, 1, 1, 2, 2, 3]
    p = strategies.StealPolicy(0, 3, 1, 0.05, 0.4)
    assert [p.backoff(f) for f in range(1, 6)] == [0.05, 0.1, 0.2, 0.4, 0.4]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
