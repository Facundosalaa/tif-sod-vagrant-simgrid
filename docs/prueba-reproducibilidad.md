# Prueba de reproducibilidad (paso 8)

Responsable: Vera, Romina (rol Inicial). Objetivo: levantar el laboratorio en una
computadora que **no** participó del desarrollo siguiendo **solamente** el
`README.md`, y anotar cada paso que falló y cómo se corrigió.

## Computadora usada

| Dato | Valor |
|---|---|
| Sistema operativo y versión | |
| Procesador / núcleos | |
| RAM | |
| ¿Hyper-V, WSL2 o Docker Desktop activos? | |
| Versión de VirtualBox | |
| Versión de Vagrant | |
| Fecha de la prueba | |

## Registro paso a paso

| # | Paso del README | Comando | ¿Funcionó? | Tiempo | Qué pasó / cómo se corrigió |
|---|---|---|---|---|---|
| 1 | Clonar el repositorio | `git clone …` | | | |
| 2 | Levantar el clúster | `vagrant up` | | | |
| 3 | Estado de las VM | `vagrant status` | | | |
| 4 | Idempotencia | `vagrant provision coord --provision-with ansible` | | | |
| 5 | Grafana | abrir http://192.168.56.10:3000 | | | |
| 6 | Una corrida real | `vagrant ssh coord -c "agrolab run --only L20-H1-ws-r1 --out /tmp/prueba"` | | | |
| 7 | Simulación equivalente | `vagrant ssh coord -c "agrolab simulate trivial"` | | | |
| 8 | Apagar y volver a encender | `vagrant halt` y `vagrant up` | | | |
| 9 | Destruir | `vagrant destroy -f` | | | |

## Cambios que hubo que hacer al repositorio

Cada falla que requirió cambiar el `README.md` o algún archivo va acá, con el
commit que la corrigió.

| Falla | Archivo corregido | Commit |
|---|---|---|
| | | |

## Prueba previa en la computadora de desarrollo

Antes de la prueba en otra computadora, se clonó el repositorio desde GitHub
en una carpeta nueva de la misma computadora de desarrollo y se levantó desde
cero siguiendo el README (ver el informe, paso 8). Esa prueba no reemplaza a
esta: la computadora de desarrollo ya tenía la box descargada y los problemas
de su entorno resueltos.
