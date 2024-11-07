from chutney.TorNet import Node


def format(n: Node) -> str:
    return f"""\
# Tor uses the first IPv6 ORPort address as its IPv6 address
OrPort {n._config.ipv6_addr}:{n._config.orport} IPv6Only

# IPv6 DirPorts are not needed
"""
