from chutney.TorNet import Node
from . import hs_v2_tmpl


def format(n: Node) -> str:
    return f"""\
# This file is a backwards-compatibility redirect
# Older chutney networks use hs.tmpl for v2 onion services
{hs_v2_tmpl.format(n)}
"""
