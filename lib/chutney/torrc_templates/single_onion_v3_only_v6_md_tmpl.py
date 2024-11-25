from chutney.TorNet import Node
from . import single_onion_v3_tmpl


def format(n: Node) -> str:
    res = single_onion_v3_tmpl.format(n)
    n._check_expected_pattern(r"^ClientUseIPv4 0", res)
    return res
