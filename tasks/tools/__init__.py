from dotenv import load_dotenv

load_dotenv()

from invoke import Collection  # noqa: E402

from tasks.tools.add import add  # noqa: E402
from tasks.tools.digests import digests  # noqa: E402
from tasks.tools.install import install  # noqa: E402
from tasks.tools.update import update  # noqa: E402

ns = Collection(update, add, install, digests)
