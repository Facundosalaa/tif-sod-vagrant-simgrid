# Bitácora individual — Salazar, Facundo

**Rol:** Investigador/a de modelado y simulación (Avanzado)
**Entregables propios:** módulo común de estrategias y carga, coordinador y trabajadores en Python, modelo SimGrid (S4U Python) y plataformas XML, calibración, validación y extrapolación.

## Semana 1 — 21/10/2026

**Qué hice**
- Leí la consigna de la Propuesta B y armé la arquitectura: 1 coordinador y 3 trabajadores en Vagrant, Ansible desde el coordinador (`ansible_local`) y SimGrid dentro del mismo coordinador.
- Elegí ZeroMQ en lugar de RabbitMQ: con VMs de 512 MB un *broker* de Erlang compite por memoria y, para el robo de trabajo, los trabajadores tienen que hablar entre sí sin pasar por el coordinador.
- Escribí el paquete `agrolab`: generador de carga con semilla, las tres estrategias en un módulo común (`strategies.py`), el protocolo de mensajes, el trabajador (dos hilos: comunicaciones y ejecutor) y el coordinador (un hilo con bucle de eventos).
- Escribí el modelo de SimGrid con la misma estructura de actores que el sistema real y el generador de plataformas XML en estrella.
- Probé coordinador y trabajadores en `localhost` antes de tener las VMs (`tests/smoke_local.py`) y escribí pruebas del módulo común.

**Qué aprendí**
- Que para que simulación y realidad ejecuten "el mismo algoritmo" lo más seguro es que importen el mismo código, no reescribirlo dos veces.
- Que en ZeroMQ el `ROUTER` descarta en silencio los mensajes a destinos desconocidos salvo que se active `ROUTER_MANDATORY`; activarlo hizo que los errores de conexión aparezcan.
- Que para no comparar relojes de máquinas distintas conviene medir todo con el reloj del coordinador y que el trabajador informe solo duraciones.

**Dificultades que encontré**
- La prueba local falló porque la función que arma los mensajes tenía un parámetro `kind` y el mensaje de tarea también tenía un campo `kind`.
- `vagrant up` falló con `E_ACCESSDENIED`: VirtualBox tenía registrada una VM vieja cuyos archivos ya no existían, y Vagrant consulta los puertos de todas las VMs registradas.
- Las VMs quedaban colgadas en "Loading essential drivers". El anfitrión tiene Hyper-V activo y VirtualBox corre encima; con 2 vCPU el arranque se colgaba en forma intermitente.

**Cómo las resolví**
- Hice el primer parámetro de `pack()` solo posicional.
- Desregistré la VM huérfana (con copia de seguridad del registro de VirtualBox).
- Probé por separado chipset, paravirtualización y cantidad de vCPU; solo 1 vCPU arrancó siempre, así que todas las VMs quedaron con 1 vCPU y la heterogeneidad se controla con `CPUQuota`.

<!-- Completar las semanas siguientes con calibración, validación y extrapolación -->

## Reflexión final desde el rol

_Completar al cierre del trabajo._
