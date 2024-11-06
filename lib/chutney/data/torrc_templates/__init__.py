from chutney.Templating import Template, Environ


def format(env: Environ) -> str:
    t = Template(
        """\

"""
    )
    return t.format(env)
