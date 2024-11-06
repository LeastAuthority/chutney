from chutney.Templating import Template
from chutney.TorNet import TorEnviron


def format(env: TorEnviron) -> str:
    t = Template(
        """\
${include:client.tmpl}
${include:client-only-v6.i}
"""
    )
    return t.format(env)
