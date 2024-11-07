from chutney.TorNet import NodeConfig
from . import relay_non_exit_tmpl, orport_v6_i


def format(n: NodeConfig) -> str:
    return f"""\
{relay_non_exit_tmpl.format(n)}

# A relay that has an IPv6 ORPort
{orport_v6_i.format(n)}
"""
