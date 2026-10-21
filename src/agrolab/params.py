"""Lectura de experiments/params.toml (única fuente de los parámetros)."""
import os
import pathlib
import tomllib

REPO = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_PATH = REPO / "experiments" / "params.toml"


def load(path: str | os.PathLike | None = None) -> dict:
    path = pathlib.Path(path or os.environ.get("AGROLAB_PARAMS", DEFAULT_PATH))
    with open(path, "rb") as f:
        return tomllib.load(f)


def quotas(params: dict, level: str, workers: list[str]) -> dict[str, int]:
    """CPUQuota (%) de cada trabajador para un nivel de heterogeneidad.
    El patrón del nivel se repite si hay más trabajadores que valores."""
    pattern = params["hetero"][level]
    return {w: pattern[i % len(pattern)] for i, w in enumerate(workers)}
