import re

from chutney.TorNet import Node
from . import client_tmpl, client_only_v6_i


def format(n: Node) -> str:
    res = f"""\
{client_tmpl.format(n)}
{client_only_v6_i.format(n)}
"""
    assert re.search(r"^ClientUseIPv4 0", res, re.MULTILINE), res
    return res
