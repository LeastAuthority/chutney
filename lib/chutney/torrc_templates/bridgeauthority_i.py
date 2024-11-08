from chutney.TorNet import TorEnviron


def format(env: TorEnviron) -> str:
    return f"""\
AuthoritativeDirectory 1
BridgeAuthoritativeDir 1
ContactInfo bridgeauth{env.nodenum}@test.test
"""
