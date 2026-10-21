"""agrolab <subcomando> [opciones]

  worker      trabajador (lo ejecuta systemd en cada VM)
  plan        genera la planilla de corridas
  run         ejecuta la planilla en el clúster real
  calibrate   mide el clúster real y escribe calibration.json
  simulate    simulaciones SimGrid (trivial | validate | scale)
"""
import importlib
import sys

COMMANDS = {
    "worker": ("agrolab.worker", "main"),
    "plan": ("agrolab.runner", "main_plan"),
    "run": ("agrolab.runner", "main_run"),
    "calibrate": ("agrolab.calibrate", "main"),
    "simulate": ("agrolab.sim", "main"),
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(0 if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help") else 2)
    module, func = COMMANDS[sys.argv[1]]
    getattr(importlib.import_module(module), func)(sys.argv[2:])


if __name__ == "__main__":
    main()
