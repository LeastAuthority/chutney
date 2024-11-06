from chutney.Templating import Template
from chutney.TorNet import TorEnviron


def format(env: TorEnviron) -> str:
    t = Template(
        """\
${include:relay-non-exit.tmpl}
${include:bridgeauthority.i}
"""
    )
    return t.format(env)
