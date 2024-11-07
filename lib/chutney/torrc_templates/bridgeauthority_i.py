from chutney.TorNet import Node


def format(n: Node) -> str:
    return f"""\
AuthoritativeDirectory 1
BridgeAuthoritativeDir 1
ContactInfo bridgeauth{n._config.nodenum}@test.test
"""
