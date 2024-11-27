from chutney.TorNet import Node
from . import relay_non_dir_tmpl


def format(n: Node) -> str:
    res = relay_non_dir_tmpl.format(n)
    n._check_expected_pattern("^DirPort [1-9]", res)
    return res
