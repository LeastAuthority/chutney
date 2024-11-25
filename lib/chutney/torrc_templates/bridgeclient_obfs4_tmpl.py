from chutney.TorNet import Node
from . import bridgeclient_tmpl


def format(n: Node) -> str:
    res = bridgeclient_tmpl.format(n)
    n._check_expected_pattern(r"^ClientTransportPlugin obfs4", res)
    return res
