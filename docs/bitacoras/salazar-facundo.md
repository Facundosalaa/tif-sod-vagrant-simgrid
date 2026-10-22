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

**Calibración (21/10, paso 6)**
- Medí la velocidad de cada VM con la tarea de referencia (unas 53 000 unidades/s sin límite; con CPUQuota 60 % da 33 000, con 50 % 28 000 y con 30 % 16 000) y el tiempo de ida de mensajes de 0 a 256 KiB con 0, 1, 20 y 100 ms de netem.
- Verifiqué el modelo con una tarea y un nodo: el tiempo simulado coincide con la cuenta a mano (diferencia relativa del orden de 10⁻⁷).

**Qué aprendí**
- El ancho de banda "efectivo" que se mide con mucha latencia (0,47 MB/s con 100 ms) no es la capacidad de la red: es lo que rinde *una* conexión TCP con su ventana. Multiplicando rendimiento por ida y vuelta da una ventana casi constante (100 a 140 KiB) en los cuatro niveles. Si hubiera usado ese valor como capacidad de los enlaces, el simulador habría predicho que a gran escala el enlace del coordinador se satura con muy poco tráfico. Lo corregí: el enlace del coordinador tiene la capacidad medida sin netem y el de cada trabajador, el rendimiento de una conexión.

**Dificultades**
- Cambié archivos del simulador mientras corría la campaña real y la columna con el *hash* del código cambió en dos corridas, aunque el código medido era el mismo. Aparté los cambios hasta el final de la campaña y repetí esas dos corridas para que todo el conjunto de datos tenga la misma versión.

**Validación y extrapolación (21/10, pasos 6 y 7)**
- Simulé las 18 configuraciones del clúster con las mismas semillas: el makespan simulado se apartó del real un 1,1 % en promedio (máximo 6,8 %) y el orden de las estrategias fue el mismo en las 6 condiciones. La espera media se apartó hasta un 28 %: el modelo no tiene los costos de Python de cada mensaje.
- Extrapolé de 3 a 512 trabajadores (270 simulaciones) y agregué 384, 640 y 768 para ver el codo: el límite del coordinador es su enlace de red, cerca de 490 trabajadores; su CPU nunca pasó del 16 %.

**Reproducibilidad (21/10, pasos 1 y 8)**
- Hice el ciclo `vagrant halt` / `vagrant up` / `vagrant destroy -f` y después cloné el repositorio desde GitHub en otra carpeta y lo levanté siguiendo solo el README: 18,4 minutos, sin intervención. La misma corrida de prueba dio 40,41 s contra 40,50 s de la campaña original, y 40,03 s en SimGrid.

**Qué aprendí**
- Que el simulador se puede usar para decidir (el orden de las estrategias no cambió en ninguna escala) pero no para dar números finos: la espera y el desbalance son las métricas donde más se nota lo que el modelo deja afuera.
- Que Grafana, con el tablero refrescándose cada 5 s, llegó a ocupar casi 1 GB del coordinador en dos horas y frenó las simulaciones hasta que lo reinicié.

## Reflexión final desde el rol

_Completar al cierre del trabajo._
