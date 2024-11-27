from chutney.TorNet import Node
from . import relay_non_exit_tmpl


def format(n: Node) -> str:
    res = relay_non_exit_tmpl.format(n)
    n._check_expected_pattern(r"^OrPort.*IPv6Only", res)
    return res
