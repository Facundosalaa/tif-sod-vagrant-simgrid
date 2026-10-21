# -*- mode: ruby -*-
# Laboratorio AgroLab: 1 coordinador + N trabajadores heterogéneos.
#
#   vagrant up                     # levanta todo y aprovisiona con Ansible
#   N_WORKERS=2 vagrant up         # otra cantidad de trabajadores (1..9)
#   vagrant provision coord        # vuelve a correr Ansible (debe dar changed=0)
#
# Los trabajadores se definen antes que el coordinador: Vagrant los levanta en
# ese orden y, cuando llega al coordinador, ya existen sus claves SSH para que
# Ansible (instalado dentro del coordinador) pueda aprovisionarlos.

N_WORKERS = Integer(ENV.fetch("N_WORKERS", "3"))
raise "N_WORKERS debe estar entre 1 y 9" unless (1..9).cover?(N_WORKERS)

BOX       = "bento/ubuntu-24.04"
NET       = "192.168.56"
COORD_IP  = "#{NET}.10"

# Perfiles de hardware de los trabajadores (se repiten si N_WORKERS > 3).
# La velocidad efectiva de cada uno se controla con CPUQuota (cgroups), según
# el nivel de heterogeneidad de experiments/params.toml.
WORKER_PROFILES = [
  { memory: 640 },  # equipo nuevo
  { memory: 512 },  # equipo intermedio
  { memory: 512 },  # equipo viejo
]

workers = (1..N_WORKERS).map do |i|
  { name: "w#{i}", ip: "#{NET}.#{10 + i}", index: i - 1 }.merge(WORKER_PROFILES[(i - 1) % WORKER_PROFILES.size])
end

# Inventario de Ansible generado a partir de la misma definición.
inventory = +"[coordinator]\n"
inventory << "coord ansible_connection=local lab_ip=#{COORD_IP}\n\n[workers]\n"
workers.each do |w|
  inventory << "#{w[:name]} ansible_host=#{w[:ip]} lab_ip=#{w[:ip]} worker_index=#{w[:index]} " \
               "ansible_ssh_private_key_file=/home/vagrant/.ssh/lab_#{w[:name]}\n"
end
inventory << "\n[all:vars]\nansible_user=vagrant\nansible_python_interpreter=/usr/bin/python3\n"
File.write(File.join(__dir__, "provisioning", "inventory.ini"), inventory)

Vagrant.configure("2") do |config|
  config.vm.box = BOX
  config.vm.box_check_update = false
  config.vm.boot_timeout = 600

  config.vm.provider "virtualbox" do |vb|
    # Un solo vCPU por VM. En un anfitrión Windows con Hyper-V activo (WSL2,
    # Docker Desktop) VirtualBox corre sobre la API de Hyper-V y, con 2 vCPU,
    # el kernel queda colgado al azar en "Loading essential drivers" (un vCPU
    # gira al 100 % esperando al otro). Con 1 vCPU arranca siempre. Las
    # aplicaciones del laboratorio son de un solo hilo, y la velocidad de cada
    # trabajador se fija con CPUQuota.
    vb.cpus = 1
  end

  workers.each do |w|
    config.vm.define w[:name] do |node|
      node.vm.hostname = w[:name]
      node.vm.network "private_network", ip: w[:ip]
      # Los trabajadores no necesitan la carpeta del proyecto: el código les
      # llega por Ansible.
      node.vm.synced_folder ".", "/vagrant", disabled: true
      node.vm.provider "virtualbox" do |vb|
        vb.name = "agrolab-#{w[:name]}"
        vb.memory = w[:memory]
        vb.linked_clone = true
      end
    end
  end

  config.vm.define "coord", primary: true do |node|
    node.vm.hostname = "coord"
    node.vm.network "private_network", ip: COORD_IP
    # Permisos fijos en la carpeta compartida: sin esto, en anfitriones Windows
    # todos los archivos aparecen como ejecutables y Ansible trata el
    # inventario como script e ignora ansible.cfg por "world writable".
    node.vm.synced_folder ".", "/vagrant", mount_options: ["dmode=755", "fmode=644"],
                          SharedFoldersEnableSymlinksCreate: false
    node.vm.provider "virtualbox" do |vb|
      vb.name = "agrolab-coord"
      vb.memory = 1536
      vb.linked_clone = true
    end

    node.vm.provision "bootstrap", type: "shell", path: "provisioning/bootstrap-coord.sh",
                      args: workers.map { |w| w[:name] }

    node.vm.provision "ansible", type: "ansible_local" do |ansible|
      ansible.install        = false            # lo instala bootstrap-coord.sh
      ansible.compatibility_mode = "2.0"
      ansible.provisioning_path = "/vagrant/provisioning"
      ansible.config_file    = "/vagrant/provisioning/ansible.cfg"
      ansible.inventory_path = "inventory.ini"
      ansible.playbook       = "site.yml"
      ansible.limit          = "all"
    end
  end
end
