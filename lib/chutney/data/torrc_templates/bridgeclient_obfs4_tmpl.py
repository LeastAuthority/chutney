from chutney.Templating import Template, Environ


def format(env: Environ) -> str:
    t = Template(
        """\
${include:bridgeclient.tmpl}

ClientTransportPlugin obfs4 exec ${path:obfs4proxy}
"""
    )
    return t.format(env)
