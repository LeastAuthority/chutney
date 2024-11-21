import re

from chutney.TorNet import Node
from . import common_i


def format(n: Node) -> str:
    res = common_i.format(n)
    assert re.search(r"^HiddenServiceSingleHopMode 1", res, flags=re.MULTILINE), res
    assert re.search(r"^HiddenServiceVersion 3", res, flags=re.MULTILINE), res
    return res
