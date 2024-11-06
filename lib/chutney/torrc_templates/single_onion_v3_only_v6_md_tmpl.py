from chutney.Templating import Template, Environ


def format(env: Environ) -> str:
    t = Template(
        """\
${include:single-onion-v3.tmpl}
# Onion services are just another kind of client
${include:client-only-v6-md.i}
"""
    )
    return t.format(env)
