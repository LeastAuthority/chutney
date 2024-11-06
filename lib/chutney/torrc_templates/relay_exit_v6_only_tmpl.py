from chutney.Templating import Template, Environ


def format(env: Environ) -> str:
    t = Template(
        """\
${include:relay-v6.tmpl}
"""
    )
    return t.format(env)
