import collections
import logging
import os

import pprint

from keystoneclient.v3 import client as keystone_client
from keystoneclient import exceptions as ks_exceptions
import yaml

from servizor.cmd import base
from servizor import service


class Install(base.BaseCommand):
    "A simple command that prints a message."

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Install, self).get_parser(prog_name)
        parser.add_argument(
            '-f', '--file', help='File to load.', action='append')
        parser.add_argument(
            '-e', '--environment', help='Environment to use', required=True)
        return parser

    def _check_unique(self, data):
        return [x for x, y in collections.Counter(data).items() if y > 1]

    def _load_file(self, f):
        """
        Return contents of the file.
        """
        if not os.path.exists(f):
            msg = '%s is a non-existant definition file' % f
            raise ValueError(msg)

        with open(f, 'r') as fh:
            return yaml.load(fh.read())

    def _load_def_files(self, files):
        duplicates = self._check_unique(files)
        if duplicates:
            msg = 'Definition file(s) found multiple times %s' % ", "\
                .join(duplicates)
            raise ValueError(msg)

        defs = {
            'services': service.Services()
        }

        for f in files:
            for i in self._load_file(f):
                self._load_def(defs, i)
        return defs

    def _load_def(self, defs, data):
        for key, values in data.items():
            if key in ('service', 'svc'):
                self.log.debug('Loading service %s' % values)
                defs['services'].get_or_create(values)
            elif key in ('endpoints', 'endpoint'):
                self.log.debug('Loading endpoint %s' % data)
                if 'service' not in values:
                    raise ValueError('Endpoint needs to belong to a service')

                # Endpoints in the end always belong to services
                svc = defs['services'].get_or_create(values['service'])
                for endpoint in values.get('entries', []):
                    svc.add_endpoint(endpoint)

            elif key in ('env', 'environmnt'):
                defs.setdefault('environment', {})
                defs['environment'][values['name']] = values['parameters']
            else:
                raise Exception("Don't know how to handle key %s" % key)

    def keystone(self):
        return keystone_client.Client(
            auth_url=self.app.options.os_auth_url,
            #endpoint=args.endpoint,
            insecure=self.app.options.insecure,

            username=self.app.options.os_username,
            project_name=self.app.options.os_project_name,
            password=self.app.options.os_password)

    def _create_or_update_service(self, ksclient, svc):
        try:
            ks_svc = ksclient.services.find(type=svc.type)
            self.log.info(
                'Updating existing service %s with id %s', svc, ks_svc.id)
            ks_svc = ksclient.services.update(
                ks_svc, name=svc.name, description=svc.description)
        except ks_exceptions.NotFound:
            msg = "Service %s/%s doesn't exist, creating it"
            self.log.info(msg % (svc.type, svc.name))

            ks_svc = ksclient.services.create(
                name=svc.name,
                type=svc.type,
                description=svc.description)
        return ks_svc

    def _create_or_update_endpoint(self, ksclient, svc, ks_svc, endpoint,
                                   params):
        endpoints = ksclient.endpoints.list(
            service=ks_svc.id,
            region=endpoint.region,
            interface=endpoint.interface)

        try:
            ep_url = endpoint.url.format(**params)
        except TypeError:
            msg = 'Params %s not sufficient to format url %s'
            self.log.warning(msg, params, endpoint.url)
            raise

        if len(endpoints) == 1:
            ks_ep = endpoints[0]
            msg = "Updating existing %s endpoint with id %s"
            msg += "\n\tCurrent: %s New: %s"
            self.log.info(msg, endpoint, ks_ep.id,
                          ks_ep.url, ep_url)
            ksclient.endpoints.update(
                ks_ep, url=ep_url)
        else:
            self.log.info('Creating %s endpoint for %s', endpoint, svc)
            ks_ep = ksclient.endpoints.create(
                service=ks_svc.id,
                url=ep_url,
                interface=endpoint.interface,
                region=endpoint.region)
        return ks_ep

    def take_action(self, parsed_args):
        self.log.info("Loading definitions from %s" % parsed_args.file)

        defs = self._load_def_files(parsed_args.file)
        env_params = defs['environment'][parsed_args.environment]

        self.log.info("Using environment settings %s", parsed_args.environment)

        ksclient = self.keystone()

        def _env(source, original, keys=['proto', 'addr', 'port']):
            new = original.copy()
            for key in keys:
                if key in source:
                    new[key] = source[key]
            return new

        for svc in iter(defs['services']):
            self.log.info("--== %s ==--" % svc)

            ks_svc = self._create_or_update_service(ksclient, svc)

            # Update with env params
            svc_params = _env(env_params, svc.parameters)

            # Can define a service without any endpoints.
            if not svc.endpoints:
                self.log.warning('Service %s doesn\'t have endpoints' % svc)
                continue

            # Push the endpoints to KS
            for endpoint in svc.endpoints:
                params = svc_params.copy()

                interface_params = env_params.get(endpoint.interface)
                if interface_params:
                    self.log.debug("Overrides found for %s",
                                   endpoint.interface)
                    params = _env(interface_params, params)

                # If there's a override for this environment for the service
                # type use it
                env_svc_params = env_params.get(svc.type)
                if env_svc_params is not None:
                    self.log.debug("Overrides found for %s" % svc.type)
                    params = _env(env_svc_params, params)

                    # If there's a override for the specific interface for the
                    # type use it
                    if endpoint.interface in env_svc_params:
                        self.log.debug("Found interface %s overrides",
                                       endpoint.interface)
                        params = _env(
                            env_svc_params[endpoint.interface], params)
                self._create_or_update_endpoint(
                    ksclient, svc, ks_svc, endpoint, params)
