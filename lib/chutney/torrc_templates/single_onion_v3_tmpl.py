from chutney.TorNet import Node
from . import common_i


def format(n: Node) -> str:
    res = common_i.format(n)
    n._check_expected_pattern(r"^HiddenServiceSingleHopMode 1", res)
    n._check_expected_pattern(r"^HiddenServiceVersion 3", res)
    return res
