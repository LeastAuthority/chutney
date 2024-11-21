import re

from chutney.TorNet import Node
from . import client_tmpl


def format(n: Node) -> str:
    res = client_tmpl.format(n)
    assert re.search(r"^UseBridges 1", res, re.MULTILINE), res
    assert re.search(r"^Bridge ", res, re.MULTILINE), res
    return res
