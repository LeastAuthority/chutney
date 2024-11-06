from chutney.Templating import Template, Environ


def format(env: Environ) -> str:
    t = Template(
        """\
${include:bridge.tmpl}

# A bridge that has an IPv6 ORPort
${include:orport-v6.i}
"""
    )
    return t.format(env)
