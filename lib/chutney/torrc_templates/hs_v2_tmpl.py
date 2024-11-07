from chutney.TorNet import NodeConfig
from . import hs_common_i


def format(n: NodeConfig) -> str:
    return f"""\
{hs_common_i.format(n)}

# Tor 0.3.4 and earlier default to 2, but 0.3.5 and later default to 3
HiddenServiceVersion 2
"""
