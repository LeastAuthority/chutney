from chutney.Templating import Template, Environ


def format(env: Environ) -> str:
    t = Template(
        """\
${include:client.tmpl}
${include:client-only-v6.i}
"""
    )
    return t.format(env)
