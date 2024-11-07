from chutney.TorNet import NodeConfig
from . import relay_v6_tmpl


def format(n: NodeConfig) -> str:
    return f"""\
{relay_v6_tmpl.format(n)}
"""
