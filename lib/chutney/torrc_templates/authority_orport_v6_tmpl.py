from chutney.TorNet import Node
from . import authority_tmpl


def format(n: Node) -> str:
    res = authority_tmpl.format(n)
    n._check_expected_pattern(r"^OrPort.*IPv6Only", res)
    n._check_expected_pattern(r"^AuthDirHasIPv6Connectivity 1", res)
    return res
