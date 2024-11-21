import re

from chutney.TorNet import Node
from . import common_i


def format(n: Node) -> str:
    res = f"""\
{common_i.format(n)}

# Tor 0.3.4 and earlier default to 2, but 0.3.5 and later default to 3
HiddenServiceVersion 3
"""
    assert re.search(r"^SocksPort 0", res, flags=re.MULTILINE), res
    assert re.search(r"^HiddenServicePort [1-9]", res, flags=re.MULTILINE), res
    return res
