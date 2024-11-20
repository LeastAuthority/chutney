import re

from chutney.TorNet import Node
from . import relay_non_dir_tmpl


def format(n: Node) -> str:
    res = relay_non_dir_tmpl.format(n)
    assert re.search("^DirPort [1-9]", res, flags=re.MULTILINE), res
    return res
