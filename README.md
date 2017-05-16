# fuel-devops-driver-ironic
Driver for fuel-devops to manage baremetal nodes using existing Ironic service

Example for using with Ironic standalone service
------------------------------------------------

1. Install fuel-devops and fuel-devops-driver-ironic
====================================================

    sudo apt-get install --yes \
        git libyaml-dev libffi-dev python-dev python-pip \
        qemu qemu-utils libvirt-bin libvirt-dev
        vlan bridge-utils ebtables pm-utils \
        genisoimage libsqlite3-0 python-virtualenv \
        libgmp-dev libssl-dev pkg-config

    virtualenv venv-devops30
    . venv-devops30/bin/activate
    pip install git+git://github.com/openstack/fuel-devops.git
    pip install git+git://github.com/dis-xcom/fuel-devops-driver-ironic.git
    dos-manage.py migrate

2. [optional] Create a node with Ironic standalone service
==========================================================

You can use the steps from here: https://github.com/dis-xcom/underpillar ,
or create a VM for ironic service using the devops template from this repo.

To do it, a single-VM fuel-devops environment will be used:

    wget https://cloud-images.ubuntu.com/xenial/current/xenial-server-cloudimg-amd64-disk1.img \
        -O /tmp/xenial-server-cloudimg-amd64.qcow2
    git clone https://github.com/dis-xcom/fuel-devops-driver-ironic


    export BAREMETAL_ADMIN_IFACE=enp8s0f1  # Interface on this fuel-devops node
                                           # that have access to PXE network for provisioning.
                                           # VM will be connected to this interface using
                                           # it's internal ens4 interface.
    export IMAGE_PATH1604=/tmp/xenial-server-cloudimg-amd64.qcow2
    export IRONIC_ENV_NAME=ironic_standalone

    dos.py create-env fuel-devops-driver-ironic/devops_driver_ironic/templates/ironic-standalone.yaml
    dos.py start $IRONIC_ENV_NAME


Then, wait for 10-15 min until the ironic-master node is deployed with cloudinit script.
During the deploy, SSH access is disabled (port 22 blocked), so the opening of the port 22
means that the Ironic has been deployed successfully.

    # Let's check that Ironic API is avaliable
    export OS_AUTH_TOKEN=fake-token
    export IRONIC_URL=http://10.50.0.2:6385/

    ironic node-list
    ironic driver-list


3. Deploy baremetal nodes with Ironic
=====================================

IRONIC_URL is used to access Ironic API from fuel-devops.
IRONIC_PXE_INTERFACE_ADDRESS is an address assigned to the interface on the Ironic node
which is used for DHCP/PXE/HTTP access from the deploying baremetal nodes.

If Ironic node was created in step #2, then on this node:
- ens3 will have the IP 10.50.0.2/24 for external access (from the host),
- ens4 will have 10.0.175.2 as a DHCP/PXE/HTTP server.

    export OS_AUTH_TOKEN=fake-token
    export IRONIC_URL=http://10.50.0.2:6385/
    export IRONIC_PXE_INTERFACE_ADDRESS=10.0.175.2
    export IRONIC_AGENT_KERNEL_URL=http://${IRONIC_PXE_INTERFACE_ADDRESS}:8080/coreos_production_pxe.vmlinuz
    export IRONIC_AGENT_RAMDISK_URL=http://${IRONIC_PXE_INTERFACE_ADDRESS}:8080/coreos_production_pxe_image-oem.cpio.gz
    export IRONIC_SOURCE_IMAGE_URL=http://${IRONIC_PXE_INTERFACE_ADDRESS}:8080/xenial-server-cloudimg-amd64.qcow2

    # Assume that downloaded image is the same as placed in the Ironic node in /httpboot/
    export IRONIC_SOURCE_IMAGE_CHECKSUM=`md5sum /tmp/xenial-server-cloudimg-amd64.qcow2 | awk '{print $1}'`

    # Set here IPMI credentials for slave01 baremetal node and MAC address of the PXE interface
    export SLAVE01_PXE_MAC_ADDRESS=
    export SLAVE01_IPMI_USER=
    export SLAVE01_IPMI_PASSWORD=
    export SLAVE01_IPMI_HOST=

    export ENV_NAME=baremetal_lab_deploy
    dos.py create-env fuel-devops-driver-ironic/devops_driver_ironic/templates/deploy_nodes.yaml

If all settings are Ok, Ironic will bootstrap the specified in the '../deploy_nodes.yaml' node using
agent and will deploy the node using IRONIC_SOURCE_IMAGE_URL image and cloudinit user-data '../deploy_nodes--user-data.yaml'