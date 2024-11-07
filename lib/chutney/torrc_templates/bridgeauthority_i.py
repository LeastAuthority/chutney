from chutney.TorNet import NodeConfig


def format(n: NodeConfig) -> str:
    return f"""\
AuthoritativeDirectory 1
BridgeAuthoritativeDir 1
ContactInfo bridgeauth{n.nodenum}@test.test
"""
