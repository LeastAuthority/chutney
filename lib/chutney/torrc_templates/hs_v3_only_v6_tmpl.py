import re

from chutney.TorNet import Node
from . import hs_v3_tmpl, client_only_v6_i


def format(n: Node) -> str:
    res = f"""\
{hs_v3_tmpl.format(n)}
# Hidden services are just another kind of client
{client_only_v6_i.format(n)}
"""
    assert re.search(r"^ClientUseIPv4 0", res, re.MULTILINE), res
    return res
