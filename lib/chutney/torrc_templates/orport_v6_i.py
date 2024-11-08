from chutney.TorNet import TorEnviron


def format(env: TorEnviron) -> str:
    return f"""\
# Tor uses the first IPv6 ORPort address as its IPv6 address
OrPort {env.ipv6_addr}:{env.orport} IPv6Only

# IPv6 DirPorts are not needed
"""
