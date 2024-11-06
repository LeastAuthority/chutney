from chutney.Templating import Template, Environ


def format(env: Environ) -> str:
    t = Template(
        """\
${include:common.i}
SocksPort $socksport
"""
    )
    return t.format(env)
