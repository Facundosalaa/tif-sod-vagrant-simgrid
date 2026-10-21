"""AgroLab: planificación y balanceo de carga en un clúster heterogéneo.

El mismo paquete corre en tres lugares:
  - los trabajadores reales (agrolab.worker, servicio systemd en cada VM),
  - el coordinador real (agrolab.coordinator / agrolab.runner),
  - el simulador SimGrid (agrolab.sim).

La lógica de decisión de cada estrategia vive en agrolab.strategies y la
generación de la carga en agrolab.workload; los dos mundos importan esos
módulos, así que ejecutan exactamente el mismo algoritmo con la misma semilla.
"""
import hashlib
import pathlib

__version__ = "1.0.0"


def code_hash() -> str:
    """Hash corto del código del paquete, para verificar que coordinador y
    trabajadores ejecutan la misma versión."""
    h = hashlib.sha256()
    pkg = pathlib.Path(__file__).parent
    for path in sorted(pkg.glob("*.py")):
        h.update(path.name.encode())
        h.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:12]
