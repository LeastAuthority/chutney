import re

from chutney.TorNet import Node
from . import relay_non_exit_tmpl


def format(n: Node) -> str:
    res = relay_non_exit_tmpl.format(n)
    assert re.search(r"^Nickname relay1mbyteMBR", res, re.MULTILINE), res
    assert re.search(r"^RelayBandwidthRate 1 MBytes", res, re.MULTILINE), res
    return res
