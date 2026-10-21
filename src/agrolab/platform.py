"""Archivos de plataforma SimGrid (XML) equivalentes al clúster de Vagrant.

Topología en estrella: cada host (coordinador y trabajadores) tiene un enlace
propio hasta un conmutador, igual que la red privada de VirtualBox. Un mensaje
entre dos hosts atraviesa dos enlaces, así que cada enlace lleva la mitad de la
latencia de ida medida.

La velocidad de los hosts se expresa en unidades de trabajo por segundo (el
simulador las llama "flops"): una tarea de C unidades tarda C / velocidad.
"""
from xml.sax.saxutils import quoteattr


def build_xml(coord_speed: float, worker_speeds: list[float], latency_s: float, bandwidth_Bps: float) -> str:
    names = [f"w{i + 1}" for i in range(len(worker_speeds))]
    hosts = [("coord", coord_speed)] + list(zip(names, worker_speeds))
    lines = [
        "<?xml version='1.0'?>",
        '<!DOCTYPE platform SYSTEM "https://simgrid.org/simgrid.dtd">',
        '<platform version="4.1">',
        '  <zone id="agrolab" routing="Dijkstra">',
    ]
    for h, speed in hosts:
        lines.append(f"    <host id={quoteattr(h)} speed=\"{speed:.3f}f\"/>")
    lines.append('    <router id="switch"/>')
    for h, _ in hosts:
        lines.append(f"    <link id=\"l_{h}\" bandwidth=\"{bandwidth_Bps:.0f}Bps\" latency=\"{latency_s / 2:.9f}s\"/>")
    for h, _ in hosts:
        lines.append(f"    <route src={quoteattr(h)} dst=\"switch\"><link_ctn id=\"l_{h}\"/></route>")
    lines += ["  </zone>", "</platform>", ""]
    return "\n".join(lines)


def from_calibration(cal: dict, level: str, latency_ms: int, n_workers: int) -> tuple[str, dict]:
    """Plataforma calibrada para un nivel de heterogeneidad y de latencia.
    Con más de 3 trabajadores se repite el patrón de velocidades medido."""
    measured = list(cal["worker_speed"][level].values())
    speeds = [measured[i % len(measured)] for i in range(n_workers)]
    net = cal["network"][str(latency_ms)]
    info = {"coord_speed": cal["coord_speed"], "latency_s": net["latency_s"], "bandwidth_Bps": net["bandwidth_Bps"]}
    return build_xml(cal["coord_speed"], speeds, net["latency_s"], net["bandwidth_Bps"]), info
