#!/usr/bin/env bash
# Prepara el coordinador como nodo de control de Ansible.
# Uso (lo invoca Vagrant): bootstrap-coord.sh w1 w2 w3 ...
set -euo pipefail

if ! command -v ansible-playbook >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -q
  apt-get install -y -q --no-install-recommends ansible-core
fi

# Claves privadas que Vagrant generó para cada trabajador. En la carpeta
# compartida no se pueden dejar en 0600, así que se copian a ~/.ssh.
install -d -m 700 -o vagrant -g vagrant /home/vagrant/.ssh
for w in "$@"; do
  src="/vagrant/.vagrant/machines/${w}/virtualbox/private_key"
  if [[ ! -f "$src" ]]; then
    echo "Falta la clave de ${w}: levantar primero los trabajadores (vagrant up)." >&2
    exit 1
  fi
  install -m 600 -o vagrant -g vagrant "$src" "/home/vagrant/.ssh/lab_${w}"
done
