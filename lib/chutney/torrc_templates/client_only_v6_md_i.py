from chutney.Templating import Template, Environ


def format(env: Environ) -> str:
    t = Template(
        """\
# A client that only uses IPv6 ORPorts
ClientUseIPv4 0
"""
    )
    return t.format(env)
