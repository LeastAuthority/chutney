from chutney.Templating import Template
from chutney.TorNet import TorEnviron


def format(env: TorEnviron) -> str:
    t = Template(
        """\
${include:single-onion.tmpl}
# Onion services are just another kind of client
${include:client-only-v6-md.i}
"""
    )
    return t.format(env)
