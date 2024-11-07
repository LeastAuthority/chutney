from chutney.TorNet import Node
from . import authority_tmpl, orport_v6_i


def format(n: Node) -> str:
    return f"""\
{authority_tmpl.format(n)}

# An authority that has an IPv6 ORPort
{orport_v6_i.format(n)}

# And has IPv6 connectivity
AuthDirHasIPv6Connectivity 1
"""
