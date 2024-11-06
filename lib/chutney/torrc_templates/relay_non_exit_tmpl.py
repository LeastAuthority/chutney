from chutney.Templating import Template
from chutney.TorNet import TorEnviron


def format(env: TorEnviron) -> str:
    t = Template(
        """\
${include:relay-non-dir.tmpl}
DirPort $dirport
"""
    )
    return t.format(env)
