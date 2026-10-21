"""Archivos de plataforma SimGrid (XML) equivalentes al clúster de Vagrant.

Topología en estrella: cada host (coordinador y trabajadores) tiene un enlace
propio hasta un conmutador, igual que la red privada de VirtualBox. Un mensaje
entre dos hosts atraviesa dos enlaces, así que cada enlace lleva la mitad de la
latencia de ida medida.

La velocidad de los hosts se expresa en unidades de trabajo por segundo (el
simulador las llama "flops"): una tarea de C unidades tarda C / velocidad.
"""
from xml.sax.saxutils import quoteattr


def build_xml(coord_speed: float, worker_speeds: list[float], latency_s: float, bandwidth_Bps: float,
              worker_bw_Bps: float | None = None) -> str:
    """`bandwidth_Bps` es la capacidad del enlace del coordinador;
    `worker_bw_Bps`, la de cada trabajador (por defecto, la misma)."""
    names = [f"w{i + 1}" for i in range(len(worker_speeds))]
    hosts = [("coord", coord_speed)] + list(zip(names, worker_speeds))
    bw = {"coord": bandwidth_Bps, **{n: worker_bw_Bps or bandwidth_Bps for n in names}}
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
        lines.append(f"    <link id=\"l_{h}\" bandwidth=\"{bw[h]:.0f}Bps\" latency=\"{latency_s / 2:.9f}s\"/>")
    for h, _ in hosts:
        lines.append(f"    <route src={quoteattr(h)} dst=\"switch\"><link_ctn id=\"l_{h}\"/></route>")
    lines += ["  </zone>", "</platform>", ""]
    return "\n".join(lines)


def from_calibration(cal: dict, level: str, latency_ms: int, n_workers: int) -> tuple[str, dict]:
    """Plataforma calibrada para un nivel de heterogeneidad y de latencia.

    Red: el ancho de banda que se mide con más latencia no es un límite de la
    red sino de cada conexión TCP (ventana / RTT). Por eso el enlace del
    coordinador, que comparten todos, tiene la capacidad medida sin netem, y el
    enlace de cada trabajador el rendimiento de una conexión con la ventana
    efectiva medida, W = B_nivel * 2 * L_nivel: los mensajes hacia un mismo
    trabajador viajan por la misma conexión de ZeroMQ y se reparten ese límite.

    Con más de 3 trabajadores se repite el patrón de velocidades medido."""
    measured = list(cal["worker_speed"][level].values())
    speeds = [measured[i % len(measured)] for i in range(n_workers)]
    net = cal["network"][str(latency_ms)]
    capacity = cal["network"]["0"]["bandwidth_Bps"]
    window = net["bandwidth_Bps"] * 2 * net["latency_s"]
    per_conn = min(capacity, window / (2 * net["latency_s"]))
    info = {"coord_speed": cal["coord_speed"], "latency_s": net["latency_s"], "bandwidth_Bps": capacity,
            "tcp_window_B": window, "worker_bw_Bps": per_conn}
    return build_xml(cal["coord_speed"], speeds, net["latency_s"], capacity, per_conn), info
