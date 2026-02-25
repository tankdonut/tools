from invoke import Collection

import build
import install
import test
import update

ns = Collection()
ns.add_collection(Collection.from_module(build))
ns.add_collection(Collection.from_module(install))
ns.add_collection(Collection.from_module(test))
ns.add_collection(Collection.from_module(update))
