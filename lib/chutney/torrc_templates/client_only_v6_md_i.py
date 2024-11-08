from chutney.TorNet import TorEnviron


def format(env: TorEnviron) -> str:
    return """\
# A client that only uses IPv6 ORPorts
ClientUseIPv4 0
"""
