from chutney.TorNet import Node
from . import common_i


def format(n: Node) -> str:
    return f"""\
{common_i.format(n)}
SocksPort {n.socksport}
"""
