from chutney.Templating import Template, Environ


def format(env: Environ) -> str:
    t = Template(
        """\
${include:hs.tmpl}
# Hidden services are just another kind of client
${include:client-only-v6-md.i}
"""
    )
    return t.format(env)
