from chutney.Templating import Template
from chutney.TorNet import TorEnviron


def format(env: TorEnviron) -> str:
    t = Template(
        """\
${include:relay-non-exit.tmpl}

Nickname relay1mbyteMBR
RelayBandwidthRate 1 MBytes
"""
    )
    return t.format(env)
