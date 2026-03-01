from invoke.collection import Collection

from tasks import build, install, test, update

ns = Collection()
ns.add_collection(Collection.from_module(build))
ns.add_collection(Collection.from_module(install))
ns.add_collection(Collection.from_module(test))
ns.add_collection(Collection.from_module(update))
