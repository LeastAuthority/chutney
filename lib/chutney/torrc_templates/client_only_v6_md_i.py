from chutney.TorNet import NodeConfig


def format(n: NodeConfig) -> str:
    return """\
# A client that only uses IPv6 ORPorts
ClientUseIPv4 0
"""
