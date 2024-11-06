from chutney.Templating import Template
from chutney.TorNet import TorEnviron


def format(env: TorEnviron) -> str:
    t = Template(
        """\
${include:hs.tmpl}
# Hidden services are just another kind of client
${include:client-only-v6-md.i}
"""
    )
    return t.format(env)
