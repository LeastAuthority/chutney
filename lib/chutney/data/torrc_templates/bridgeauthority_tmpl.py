from chutney.Templating import Template, Environ


def format(env: Environ) -> str:
    t = Template(
        """\
${include:relay-non-exit.tmpl}
${include:bridgeauthority.i}
"""
    )
    return t.format(env)
