from chutney.TorNet import Node
from . import hs_v3_tmpl


def format(n: Node) -> str:
    res = hs_v3_tmpl.format(n)
    n._check_expected_pattern(r"^ClientUseIPv4 0", res)
    n._check_expected_pattern(r"^UseMicrodescriptors 0", res)
    return res
