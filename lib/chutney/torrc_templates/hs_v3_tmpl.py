import re

from chutney.TorNet import Node
from . import common_i


def format(n: Node) -> str:
    res = common_i.format(n)
    assert re.search(r"^HiddenServiceVersion 3", res, flags=re.MULTILINE), res
    assert re.search(r"^SocksPort 0", res, flags=re.MULTILINE), res
    assert re.search(r"^HiddenServicePort [1-9]", res, flags=re.MULTILINE), res
    return res
