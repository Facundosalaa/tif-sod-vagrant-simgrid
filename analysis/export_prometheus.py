"""Exporta de Prometheus el consumo de las VMs durante la campaña de corridas.

  python analysis/export_prometheus.py [--prom http://192.168.56.10:9090]

Toma el intervalo de experiments/results/real/runs.csv (desde la primera
corrida hasta el final de la última) y guarda, cada 15 s y por nodo: núcleos de
CPU usados, memoria usada y tráfico de red. Resultado:
experiments/results/real/vm_resources.csv
"""
import argparse
import csv
import datetime as dt
import json
import pathlib
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
QUERIES = {
    # CPU por proceso: en VMs sobre la API de Hyper-V, node_cpu_seconds_total
    # (contabilidad por ticks del kernel invitado) pierde parte del tiempo.
    "cpu_cores": 'rate(process_cpu_seconds_total{job="agrolab"}[30s])',
    "mem_used_mb": "(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / 1048576",
    "net_tx_kbps": 'sum by (node) (rate(node_network_transmit_bytes_total{device!="lo"}[30s])) * 8 / 1000',
    "net_rx_kbps": 'sum by (node) (rate(node_network_receive_bytes_total{device!="lo"}[30s])) * 8 / 1000',
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prom", default="http://192.168.56.10:9090")
    ap.add_argument("--step", default="15s")
    args = ap.parse_args()
    runs = list(csv.DictReader(open(ROOT / "experiments/results/real/runs.csv", encoding="utf-8")))
    def utc(s):  # el coordinador registra la hora en UTC (la zona de las VM)
        t = dt.datetime.fromisoformat(s)
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    start = min(utc(r["started"]) for r in runs)
    end = max(utc(r["started"]) + dt.timedelta(seconds=float(r["wall_s"])) for r in runs)
    series = {}
    for name, q in QUERIES.items():
        url = args.prom + "/api/v1/query_range?" + urllib.parse.urlencode(
            {"query": q, "start": start.timestamp(), "end": end.timestamp(), "step": args.step})
        data = json.load(urllib.request.urlopen(url, timeout=60))["data"]["result"]
        for s in data:
            node = s["metric"].get("node", "?")
            for ts, val in s["values"]:
                series.setdefault((float(ts), node), {})[name] = float(val)
    out = ROOT / "experiments/results/real/vm_resources.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "node", *QUERIES])
        for (ts, node), vals in sorted(series.items()):
            w.writerow([dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat(timespec="seconds"), node,
                        *[round(vals.get(k, float("nan")), 3) for k in QUERIES]])
    print(f"{len(series)} filas -> {out}")


if __name__ == "__main__":
    main()
