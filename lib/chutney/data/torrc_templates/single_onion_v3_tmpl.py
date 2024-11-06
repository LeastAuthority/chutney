from chutney.Templating import Template, Environ


def format(env: Environ) -> str:
    t = Template(
        """\
${include:single-onion-common.i}
HiddenServiceVersion 3
"""
    )
    return t.format(env)
