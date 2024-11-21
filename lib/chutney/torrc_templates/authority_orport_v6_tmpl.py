import re

from chutney.TorNet import Node
from . import authority_tmpl


def format(n: Node) -> str:
    res = authority_tmpl.format(n)
    assert re.search(r"^OrPort.*IPv6Only", res, re.MULTILINE), res
    assert re.search(r"^AuthDirHasIPv6Connectivity 1", res, re.MULTILINE), res
    return res
