#    Copyright 2013 - 2016 Mirantis, Inc.
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

import datetime
import itertools
import os
import re
import shutil
import time
import uuid
import warnings
# noinspection PyPep8Naming
import xml.etree.ElementTree as ET

from django.conf import settings
from django.utils import functional
from ironicclient import client
import netaddr
import paramiko

from devops.driver.libvirt import libvirt_xml_builder as builder
from devops import error
from devops.helpers import cloud_image_settings
from devops.helpers import decorators
from devops.helpers import helpers
from devops.helpers import scancodes
from devops.helpers import ssh_client
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
        return client.get_client(
            os_auth_token=self.os_auth_token,
            ironic_url=self.ironic_url,
        )

    #def node_list(self):
    #    # virConnect.listDefinedDomains() only returns stopped domains
    #    #   https://bugzilla.redhat.com/show_bug.cgi?id=839259
    #    return [item.name() for item in self.conn.listAllDomains()]



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


    #@decorators.retry(libvirt.libvirtError)
    def exists(self):
        """Check if node exists

            :rtype : Boolean
        """
        pass
        #try:
        #    self.driver.conn.lookupByUUIDString(self.uuid)
        #    return True
        #except libvirt.libvirtError as e:
        #    if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
        #        return False
        #    else:
        #        raise

    # @decorators.retry(libvirt.libvirtError)
    def is_active(self):
        """Check if node is active

            :rtype : Boolean
        """
        pass
        # return bool(self._libvirt_node.isActive())

    #def send_keys(self, keys):
    #    """Send keys to node

    #    :type keys: String
    #        :rtype : None
    #    """
    #    key_codes = scancodes.from_string(str(keys))
    #    for key_code in key_codes:
    #        if isinstance(key_code[0], str):
    #            if key_code[0] == 'wait':
    #                time.sleep(1)
    #            continue
    #        self._libvirt_node.sendKey(0, 0, list(key_code), len(key_code), 0)

    #@decorators.retry()
    def define(self):
        """Define node

            :rtype : None
        """
        ironic_node_name = helpers.underscored(
            helpers.deepgetattr(self, 'group.environment.name'),
            self.name,
        )

        root_volume = self.get_volume(name=self.root_volume_name)

        # Necessary only once, when node is registered to ironic
        node = self.driver.conn.node.create(
            driver=self.ironic_driver,
            driver_info = {
                name = ironic_node_name,
                deploy_kernel = self.driver.agent_kernel_url,
                deploy_ramdisk = self.driver.agent_ramdisk_url,
                ipmi_address = self.ipmi_host,
                ipmi_username = self.ipmi_user,
                ipmi_password = self.ipmi_password,
            }
        )

        for interface in self.interfaces:
            if interface.mac_address:
                self.driver.conn.port.create(
                    node_uuid=node.uuid,
                    address=interface.mac_address,
                )

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
        self.driver.conn.node.update(
            node.uuid,
            patch=patch,
        )

        ############################# TODO: node-set-provision-state

        if self.cloud_init_volume_name is not None:
            self._create_cloudimage_settings_iso()

        super(IronicNode, self).define()

    def start(self):
        # power on
        #self.create()
        pass

    #@decorators.retry(libvirt.libvirtError)
    def destroy(self, *args, **kwargs):
        if self.is_active():
            pass

        #    try:
        #        self._libvirt_node.destroy()
        #    except libvirt.libvirtError as e:
        #        if e.get_error_code() == libvirt.VIR_ERR_SYSTEM_ERROR:
        #            logger.error(
        #                "Error appeared while destroying the domain"
        #                " {}, ignoring".format(self._libvirt_node.name()))
        #            return None
        #        else:
        #            raise
        super(IronicNode, self).destroy()

    #@decorators.retry(libvirt.libvirtError)
    def remove(self, *args, **kwargs):
        if self.uuid:
            if self.exists():
                self.destroy()

        super(IronicNode, self).remove()


    #@decorators.retry(libvirt.libvirtError)
    def reboot(self):
        """Reboot node

            :rtype : None
        """
        #self._libvirt_node.reboot()
        super(IronicNode, self).reboot()

    #@decorators.retry(libvirt.libvirtError)
    def shutdown(self):
        """Shutdown node

            :rtype : None
        """
        #self._libvirt_node.shutdown()
        super(IronicNode, self).shutdown()

    #@decorators.retry(libvirt.libvirtError)
    def reset(self):
        #self._libvirt_node.reset()
        super(IronicNode, self).reset()

    def _create_cloudimage_settings_iso(self):
        """Builds setting iso to send basic configuration for cloud image"""

        if self.cloud_init_volume_name is None:
            return
        volume = self.get_volume(name=self.cloud_init_volume_name)

        interface = self.interface_set.get(
            label=self.cloud_init_iface_up)
        admin_ip = self.get_ip_address_by_network_name(
            name=None, interface=interface)

        env_name = self.group.environment.name
        dir_path = os.path.join(settings.CLOUD_IMAGE_DIR, env_name)
        cloud_image_settings_path = os.path.join(
            dir_path, 'cloud_settings.iso')
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

        volume.upload(cloud_image_settings_path)

        # Clear temporary files
        if os.path.exists(dir_path):
            shutil.rmtree(dir_path)


class IronicInterface(network.Interface):
    pass
