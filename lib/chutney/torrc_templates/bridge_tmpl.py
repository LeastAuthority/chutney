from chutney.TorNet import Node
from . import relay_non_dir_tmpl


def format(n: Node) -> str:
    res = relay_non_dir_tmpl.format(n)
    n._check_expected_pattern(r"^DirPort 0", res)
    n._check_expected_pattern(r"^BridgeRelay 1", res)
    return res
