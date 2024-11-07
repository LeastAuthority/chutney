from chutney.TorNet import NodeConfig
from . import authority_tmpl, orport_v6_i


def format(n: NodeConfig) -> str:
    return f"""\
{authority_tmpl.format(n)}

# An authority that has an IPv6 ORPort
{orport_v6_i.format(n)}

# And has IPv6 connectivity
AuthDirHasIPv6Connectivity 1
"""
