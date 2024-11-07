from chutney.TorNet import NodeConfig
from . import common_i


def format(n: NodeConfig) -> str:
    return f"""\
{common_i.format(n)}
SocksPort {n.socksport}
"""
