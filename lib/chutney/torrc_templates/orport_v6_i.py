from chutney.Templating import Template
from chutney.TorNet import TorEnviron


def format(env: TorEnviron) -> str:
    t = Template(
        """\
# Tor uses the first IPv6 ORPort address as its IPv6 address
OrPort ${ipv6_addr}:${orport} IPv6Only

# IPv6 DirPorts are not needed
"""
    )
    return t.format(env)
