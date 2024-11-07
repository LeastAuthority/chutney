from chutney.TorNet import NodeConfig
from . import client_tmpl, client_only_v6_i


def format(n: NodeConfig) -> str:
    return f"""\
{client_tmpl.format(n)}
{client_only_v6_i.format(n)}
"""
