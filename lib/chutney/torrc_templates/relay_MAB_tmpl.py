from chutney.TorNet import Node
from . import relay_non_exit_tmpl


def format(n: Node) -> str:
    res = relay_non_exit_tmpl.format(n)
    n._check_expected_pattern(r"^Nickname relay1mbyteMAB", res)
    n._check_expected_pattern(r"^MaxAdvertisedBandwidth 1 MBytes", res)
    return res
