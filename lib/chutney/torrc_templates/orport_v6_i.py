from chutney.TorNet import NodeConfig


def format(n: NodeConfig) -> str:
    return f"""\
# Tor uses the first IPv6 ORPort address as its IPv6 address
OrPort {n.ipv6_addr}:{n.orport} IPv6Only

# IPv6 DirPorts are not needed
"""
