from chutney.TorNet import Node
from . import bridge_tmpl


def format(n: Node) -> str:
    res = bridge_tmpl.format(n)
    n._check_expected_pattern(r"^OrPort.*IPv6Only", res)
    return res
