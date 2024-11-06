from chutney.Templating import Template
from chutney.TorNet import TorEnviron


def format(env: TorEnviron) -> str:
    t = Template(
        """\
AuthoritativeDirectory 1
BridgeAuthoritativeDir 1
ContactInfo bridgeauth${nodenum}@test.test
"""
    )
    return t.format(env)
