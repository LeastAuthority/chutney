from chutney.TorNet import Node


def format(n: Node) -> str:
    return """\
# A client that only uses IPv6 ORPorts
ClientUseIPv4 0
"""
