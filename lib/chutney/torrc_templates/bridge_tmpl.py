import re

from chutney.TorNet import Node
from . import relay_non_dir_tmpl


def format(n: Node) -> str:
    res = relay_non_dir_tmpl.format(n)
    assert re.search(r"^DirPort 0", res, flags=re.MULTILINE), res
    assert re.search(r"^BridgeRelay 1", res, flags=re.MULTILINE), res
    return res
