import re

from chutney.TorNet import Node
from . import relay_non_exit_tmpl


def format(n: Node) -> str:
    res = relay_non_exit_tmpl.format(n)
    assert re.search(r"^OrPort.*IPv6Only", res, re.MULTILINE), res
    return res
