from chutney.Templating import Template
from chutney.TorNet import TorEnviron


def format(env: TorEnviron) -> str:
    t = Template(
        """\
${include:bridgeclient.tmpl}

ClientTransportPlugin obfs4 exec ${path:obfs4proxy}
"""
    )
    return t.format(env)
