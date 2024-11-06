from chutney.Templating import Template, Environ


def format(env: Environ) -> str:
    t = Template(
        """\
${include:relay-non-dir.tmpl}
DirPort $dirport
"""
    )
    return t.format(env)
