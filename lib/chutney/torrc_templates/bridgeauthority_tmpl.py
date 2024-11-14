from chutney.TorNet import Node
from . import relay_non_exit_tmpl, bridgeauthority_i


def format(n: Node) -> str:
    return f"""\
{relay_non_exit_tmpl.format(n)}
{bridgeauthority_i.format(n)}
"""
