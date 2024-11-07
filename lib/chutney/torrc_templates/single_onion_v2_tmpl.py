from chutney.TorNet import NodeConfig
from . import single_onion_common_i


def format(n: NodeConfig) -> str:
    return f"""\
{single_onion_common_i.format(n)}
HiddenServiceVersion 2
"""
