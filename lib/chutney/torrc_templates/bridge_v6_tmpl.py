from chutney.TorNet import NodeConfig
from . import bridge_tmpl, orport_v6_i


def format(n: NodeConfig) -> str:
    return f"""\
{bridge_tmpl.format(n)}

# A bridge that has an IPv6 ORPort
{orport_v6_i.format(n)}
"""
