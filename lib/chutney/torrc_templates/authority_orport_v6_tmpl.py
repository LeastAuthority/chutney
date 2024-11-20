import re

from chutney.TorNet import Node
from . import authority_tmpl


def format(n: Node) -> str:
    res = f"""\
{authority_tmpl.format(n)}

# And has IPv6 connectivity
AuthDirHasIPv6Connectivity 1
"""
    assert re.search(r"^OrPort.*IPv6Only", res, re.MULTILINE), res
    return res
