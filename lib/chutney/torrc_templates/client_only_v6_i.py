from chutney.TorNet import Node
from . import client_only_v6_md_i


def format(n: Node) -> str:
    return f"""\
# A client that only uses IPv6 ORPorts
{client_only_v6_md_i.format(n)}

# Due to Tor bug #19608, microdescriptors can't be used by IPv6-only clients
# running tor 0.2.9 and earlier
UseMicrodescriptors 0
"""
