from chutney.Templating import Template, Environ


def format(env: Environ) -> str:
    t = Template(
        """\
AuthoritativeDirectory 1
BridgeAuthoritativeDir 1
ContactInfo bridgeauth${nodenum}@test.test
"""
    )
    return t.format(env)
