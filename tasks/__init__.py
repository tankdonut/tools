from invoke.collection import Collection

from tasks import build, tools

ns = Collection()
ns.add_collection(Collection.from_module(build))
ns.add_collection(Collection.from_module(tools))
