class Base(object):
    def __init__(self, parameters=None):
        self.parameters = parameters or {}

    def __eq__(x, y):
        return x._key() == y._key()

    def __hash__(self):
        return hash(self._key())


class Endpoint(Base):
    def __init__(self, url, interface='public', region='RegionOne'):
        self.url = url
        self.interface = interface
        self.region = region

    def _key(self):
        return (self.interface, self.region)

    def __repr__(self):
        return '<Endpoint: %s:%s>' % (self.interface, self.region)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)


class Service(Base):
    def __init__(self, type, name, description=None, endpoints=[], **kw):
        super(Service, self).__init__(**kw)
        self.type = type
        self.name = name
        self.description = description

        self.endpoints = set()

        if endpoints:
            map(self.add_endpoint, endpoints)

    def _key(self):
        return (self.type, self.name)

    def __repr__(self):
        return '<Service: %s:%s>' % (self.type, self.name)

    def add_endpoint(self, endpoint):
        if isinstance(endpoint, dict):
            endpoint = Endpoint.from_dict(endpoint)

        if endpoint in self.endpoints:
            msg = 'Endpoint %s is not unique for %s'
            raise TypeError(msg % (endpoint.interface, self.type))

        self.endpoints.add(endpoint)

    @classmethod
    def from_dict(cls, data):
        return cls(
            data['type'], data['name'],
            description=data.get('description', None),
            endpoints=data.get('endpoints', []),
            parameters=data.get('parameters')
        )


class Services(object):
    def __init__(self):
        self.services = {}

    def get_existing(self, svc):
        if svc.type in self.services and svc.name in self.services[svc.type]:
            return self.services[svc.type][svc.name]
        else:
            raise KeyError

    def add(self, svc):
        self.services.setdefault(svc.type, {})
        self.services[svc.type][svc.name] = svc
        return svc

    def get_or_create(self, service):
        if isinstance(service, dict):
            svc = Service.from_dict(service)

        try:
            return self.get_existing(svc)
        except KeyError:
            return self.add(svc)

    def __iter__(self):
        for t in self.services.values():
            for svc in t.values():
                yield svc
