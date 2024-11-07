from chutney.TorNet import NodeConfig
from . import relay_non_exit_tmpl, bridgeauthority_i


def format(n: NodeConfig) -> str:
    return f"""\
{relay_non_exit_tmpl.format(n)}
{bridgeauthority_i.format(n)}
"""
