import re

from chutney.TorNet import Node
from . import bridge_tmpl


def format(n: Node) -> str:
    res = bridge_tmpl.format(n)
    assert re.search(r"^OrPort.*IPv6Only", res, re.MULTILINE), res
    return res
