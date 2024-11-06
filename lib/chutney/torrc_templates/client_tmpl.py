from chutney.Templating import Template
from chutney.TorNet import TorEnviron


def format(env: TorEnviron) -> str:
    t = Template(
        """\
${include:common.i}
SocksPort $socksport
"""
    )
    return t.format(env)
