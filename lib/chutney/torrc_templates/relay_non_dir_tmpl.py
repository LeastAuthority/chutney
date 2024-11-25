from chutney.TorNet import Node
from . import common_i


def format(n: Node) -> str:
    assert n._config.relay
    res = common_i.format(n)
    n._check_expected_pattern(r"^SocksPort 0", res)
    n._check_expected_pattern(r"^OrPort [1-9]", res)

    return res
