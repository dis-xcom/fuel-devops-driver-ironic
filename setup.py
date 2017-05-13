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

import setuptools


setuptools.setup(
    name='fuel-devops-driver-ironic',
    version='0.1.0',
    description=('Driver for fuel-devops to manage baremetal nodes using '
                 'existing Ironic service'),
    author='Mirantis, Inc.',
    author_email='ddmitriev@mirantis.com',
    url='http://mirantis.com',
    keywords='devops virtual environment',
    zip_safe=False,
    include_package_data=True,
    packages=setuptools.find_packages(),

    package_data={
        'devops-driver-ironic': ['templates/*.yaml', 'templates/*.yml']},
    install_requires=[
        'fuel-devops>=3.0.3',
        'python-ironicclient>=1.6.0',
    ],
    tests_require=[
        'pytest>=2.7.1',
        'pytest-django >= 2.8.0',
        'mock>=1.2',
        'tox>=2.0'
    ],
)
