#    Copyright 2013 - 2017 Mirantis, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import os
import shutil
import time

from django.conf import settings
from ironicclient import client
from ironicclient import exc

from devops import error
from devops.helpers import cloud_image_settings
from devops.helpers import decorators
from devops.helpers import helpers
from devops.helpers import subprocess_runner
from devops import logger
from devops.models import base
from devops.models import driver
from devops.models import network
from devops.models import node
from devops.models import volume


class IronicDriver(driver.Driver):
    """Ironic driver

    Note: This class is imported as Driver at .__init__.py
    """

    os_auth_token = base.ParamField()
    ironic_url = base.ParamField(default="http://localhost:6385/")

    agent_kernel_url = base.ParamField()
    agent_ramdisk_url = base.ParamField()

    @property
    def conn(self):
        """Connection to ironic api"""
        kwargs = {'os_auth_token': self.os_auth_token,
                  'ironic_url': self.ironic_url}
        return client.get_client(1, **kwargs)


class IronicL2NetworkDevice(network.L2NetworkDevice):
    """Note: This class is imported as L2NetworkDevice at .__init__.py """
    pass


class IronicVolume(volume.Volume):
    """Note: This class is imported as Volume at .__init__.py """

    capacity = base.ParamField(default=None)  # in gigabytes
    format = base.ParamField(default='qcow2', choices=('qcow2', 'raw'))
    source_image = base.ParamField(default=None)
    source_image_checksum = base.ParamField(default=None)
    cloudinit_meta_data = base.ParamField(default=None)
    cloudinit_user_data = base.ParamField(default=None)


class IronicNode(node.Node):
    """Note: This class is imported as Node at .__init__.py """

    uuid = base.ParamField()
    bootmenu_timeout = base.ParamField(default=0)
    numa = base.ParamField(default=[])
    root_volume_name = base.ParamField()
    cloud_init_volume_name = base.ParamField()
    cloud_init_iface_up = base.ParamField()

    ironic_driver = base.ParamField(default='agent_ipmitool')

    boot = base.ParamField(default='pxe')
    force_set_boot = base.ParamField(default=True)
    ipmi_user = base.ParamField()
    ipmi_password = base.ParamField()
    ipmi_previlegies = base.ParamField(default='OPERATOR')
    ipmi_host = base.ParamField()
    ipmi_lan_interface = base.ParamField(default="lanplus")
    ipmi_port = base.ParamField(default=623)

    # Required in cases of changed provisioning states
    wait_active_timeout = base.ParamField(default=900)

    def exists(self, timeout=5):
        """Check if node exists

            :rtype : Boolean
        """
        try:
            with helpers.RunLimit(timeout):
                return any([self.uuid == node.uuid
                            for node in self.driver.conn.node.list()])
        except error.TimeoutError:
            logger.error("Ironic API is not responded for {0}sec, assuming "
                         "that node {1} is absent".format(timeout, self.name))
            return False

    def is_active(self):
        """Check if node is active

            :rtype : Boolean
        """
        states = self.driver.conn.node.states(self.uuid)
        return (states['provision_state'] == 'active' and
                states['power_state'] == 'power on')

    @property
    def ironic_node_name(self):
        #return helpers.underscored(
        #    helpers.deepgetattr(self, 'group.environment.name'),
        #    self.name,
        #).replace("_", "-")
        return self.name.replace("_", "-")

    def define(self):
        """Define node

            :rtype : None
        """

        root_volume = self.get_volume(name=self.root_volume_name)

        # Necessary only once, when node is registered to ironic
        node = self.driver.conn.node.create(
            driver=self.ironic_driver,
            name=self.ironic_node_name,
            driver_info={
                'deploy_kernel': self.driver.agent_kernel_url,
                'deploy_ramdisk': self.driver.agent_ramdisk_url,
                'ipmi_address': self.ipmi_host,
                'ipmi_username': self.ipmi_user,
                'ipmi_password': self.ipmi_password,
            }
        )
        logger.debug("Created Ironic node: {0}".format(node))

        for interface in self.interfaces:
            if interface.mac_address:
                port = self.driver.conn.port.create(
                    node_uuid=node.uuid,
                    address=interface.mac_address,
                )
                logger.debug("Created Ironic node port: {0}".format(port))

        # Necessary for each deploy/redeploy
        patch = [
            {
                'path': '/instance_info/root_gb',
                'value': root_volume.capacity,
                'op': 'add'
            },
            {
                'path': '/instance_info/image_source',
                'value': root_volume.source_image,
                'op': 'add'
            },
            {
                'path': '/instance_info/image_checksum',
                'value': root_volume.source_image_checksum,
                'op': 'add'
            }
        ]

        logger.debug("Updating Ironic node with: {0}".format(patch))
        updated_node = self.driver.conn.node.update(
            node.uuid,
            patch=patch,
        )
        logger.debug("Updated Ironic node: {0}".format(updated_node))

        # TODO(ddmitriev): node-set-provision-state

        if self.cloud_init_volume_name is not None:
            configdrive = self.__create_configdrive()
        else:
            configdrive = None

        self.driver.conn.node.set_provision_state(
            node_uuid=node.uuid,
            configdrive=configdrive,
            state='active',
        )
        logger.debug("Set provision state to 'active' for node {0} {1}"
                     .format(node.name, node.uuid))

        self.uuid = node.uuid
        super(IronicNode, self).define()

    def wait_for_state(self, expected_state, timeout=600):
        threshold = time.time() + timeout
        while not timeout or time.time() < threshold:
            try:
                self.driver.conn.node.wait_for_provision_state(
                    node_ident=self.uuid,
                    expected_state='active',
                    timeout=self.wait_active_timeout)
                return
            except exc.StateTransitionFailed:
                # When node is deploying, there can be non-critical errors
                # during state transitions, let's skip them.
                time.sleep(10)
        raise exc.StateTransitionTimeout(
            'Node {0} with uuid={1} failed to reach state {2} in {3} seconds'
            .format(self.name, self.uuid, expected_state, timeout))

    def start(self):
        """Start the node (power on)"""
        logger.info("Starting Ironic node {0}(uuid={1}) with timeout={2}"
                    .format(self.name, self.uuid, self.wait_active_timeout))

        self.wait_for_state(expected_state='active',
            timeout=self.wait_active_timeout)

        self.driver.conn.node.set_power_state(
            node_id=self.uuid,
            state='on',
        )
        super(IronicNode, self).start()

    def destroy(self, *args, **kwargs):
        """Stop the node (power off)"""
        super(IronicNode, self).destroy()

        self.wait_for_state(expected_state='active',
            timeout=self.wait_active_timeout)

        self.driver.conn.node.set_power_state(
            node_id=self.uuid,
            state='off',
            soft=False,
        )

    @decorators.retry(Exception, count=10, delay=20)
    def remove(self, *args, **kwargs):
        super(IronicNode, self).remove()
        if self.uuid:
            if self.exists():
            #    self.destroy()
                logger.info("Removing Ironic node {0}(uuid={1})"
                            .format(self.name, self.uuid))

                self.driver.conn.node.set_maintenance(
                    node_id=self.uuid,
                    state=True,
                    maint_reason="Removing the node from devops environment")
                self.driver.conn.node.delete(self.uuid)

    def reboot(self):
        """Reboot node gracefully

            :rtype : None
        """
        super(IronicNode, self).reboot()

        self.wait_for_state(expected_state='active',
            timeout=self.wait_active_timeout)

        self.driver.conn.node.set_power_state(
            node_id=self.uuid,
            state='reboot',
            soft=True,
        )

    def shutdown(self):
        """Shutdown node gracefully

            :rtype : None
        """
        super(IronicNode, self).shutdown()

        self.wait_for_state(expected_state='active',
            timeout=self.wait_active_timeout)

        self.driver.conn.node.set_power_state(
            node_id=self.uuid,
            state='off',
            soft=True,
        )

    def reset(self):
        """Reboot node"""
        super(IronicNode, self).reset()

        self.wait_for_state(expected_state='active',
            timeout=self.wait_active_timeout)

        self.driver.conn.node.set_power_state(
            node_id=self.uuid,
            state='reboot',
            soft=False,
        )

    def __create_configdrive(self):
        """Builds setting iso to send basic configuration for cloud image

        Returns a gzipped, base64-encoded configuration drive string.
        """

        if self.cloud_init_volume_name is None:
            return None

        volume = self.get_volume(name=self.cloud_init_volume_name)

        interface = self.interface_set.get(
            label=self.cloud_init_iface_up)
        admin_ip = self.get_ip_address_by_network_name(
            name=None, interface=interface)

        env_name = self.group.environment.name
        dir_path = os.path.join(settings.CLOUD_IMAGE_DIR, env_name)
        cloud_image_settings_path = os.path.join(
            dir_path, 'configdrive_{0}.iso'.format(self.ironic_node_name))
        meta_data_path = os.path.join(dir_path, "meta-data")
        user_data_path = os.path.join(dir_path, "user-data")

        interface_name = interface.label
        admin_ap = interface.l2_network_device.address_pool
        gateway = str(admin_ap.gateway)
        admin_netmask = str(admin_ap.ip_network.netmask)
        admin_network = str(admin_ap.ip_network)
        hostname = self.name

        cloud_image_settings.generate_cloud_image_settings(
            cloud_image_settings_path=cloud_image_settings_path,
            meta_data_path=meta_data_path,
            user_data_path=user_data_path,
            admin_network=admin_network,
            interface_name=interface_name,
            admin_ip=admin_ip,
            admin_netmask=admin_netmask,
            gateway=gateway,
            hostname=hostname,
            meta_data_content=volume.cloudinit_meta_data,
            user_data_content=volume.cloudinit_user_data,
        )

        cmd = 'gzip -9 -c {0} | base64'.format(cloud_image_settings_path)
        result = subprocess_runner.Subprocess.check_call(cmd)

        # Clear temporary files
        if os.path.exists(dir_path):
            shutil.rmtree(dir_path)

        return ''.join(result['stdout'])


class IronicInterface(network.Interface):
    pass
