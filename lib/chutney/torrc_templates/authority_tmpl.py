from chutney.TorNet import NodeConfig
from . import relay_non_exit_tmpl, authority_i


def format(n: NodeConfig) -> str:
    return f"""\
{relay_non_exit_tmpl.format(n)}
{authority_i.format(n)}
"""
