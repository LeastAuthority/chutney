import re

from chutney.TorNet import Node
from . import common_i


def format(n: Node) -> str:
    res = f"""\
{common_i.format(n)}
HiddenServiceVersion 3
"""
    assert re.search(r"^HiddenServiceSingleHopMode 1", res, flags=re.MULTILINE), res
    return res
