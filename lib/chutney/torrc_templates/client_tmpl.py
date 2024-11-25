from chutney.TorNet import Node
from . import common_i


def format(n: Node) -> str:
    res = common_i.format(n)
    n._check_expected_pattern(r"^SocksPort [1-9]", res)
    return res
