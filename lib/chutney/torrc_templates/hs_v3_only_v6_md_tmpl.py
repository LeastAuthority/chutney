import re

from chutney.TorNet import Node
from . import hs_v3_tmpl


def format(n: Node) -> str:
    res = hs_v3_tmpl.format(n)
    assert re.search(r"^ClientUseIPv4 0", res, re.MULTILINE), res
    return res
