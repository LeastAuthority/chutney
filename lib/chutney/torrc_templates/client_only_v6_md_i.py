from chutney.Templating import Template
from chutney.TorNet import TorEnviron


def format(env: TorEnviron) -> str:
    t = Template(
        """\
# A client that only uses IPv6 ORPorts
ClientUseIPv4 0
"""
    )
    return t.format(env)
