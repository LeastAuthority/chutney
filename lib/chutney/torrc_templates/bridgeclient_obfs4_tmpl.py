import re

from chutney.TorNet import Node
from . import bridgeclient_tmpl


def format(n: Node) -> str:
    res = bridgeclient_tmpl.format(n)
    assert re.search(r"^ClientTransportPlugin obfs4", res, re.MULTILINE), res
    return res
