"""Mensajes entre coordinador y trabajadores (ZeroMQ multiparte).

Cada mensaje es un encabezado JSON y, si lleva datos, marcos binarios a
continuación. Tipos:

  coordinador -> trabajador   START, TASK, END, PING, BENCH
  trabajador -> coordinador   HELLO, READY, DONE, BYE, PONG, BENCH_OK
  trabajador -> trabajador    STEAL (pedido de robo), LOOT (respuesta)

DONE es la confirmación (acknowledgement) de cada tarea: el coordinador no da
una tarea por terminada hasta recibirla.
"""
import json

# Tamaño típico de un encabezado serializado; el simulador lo suma a los datos
# de cada mensaje.
HEADER_BYTES = 160


def pack(msg_type: str, /, **fields) -> bytes:
    return json.dumps({"k": msg_type, **fields}, separators=(",", ":")).encode()


def unpack(frame: bytes) -> dict:
    return json.loads(frame)
