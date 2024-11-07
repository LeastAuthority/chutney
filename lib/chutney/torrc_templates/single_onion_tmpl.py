from chutney.TorNet import NodeConfig
from . import single_onion_v2_tmpl


def format(n: NodeConfig) -> str:
    return f"""\
# This file is a backwards-compatibility redirect
# Older chutney networks use single-onion.tmpl for v2 single onion services
{single_onion_v2_tmpl.format(n)}
"""
