import ipdb
ipdb.set_trace()


class Test(object):
    def __hash__(self):
        return hash("1")


unique = set()
unique.add(Test())
unique.add(Test())

print unique