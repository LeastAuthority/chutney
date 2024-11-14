from chutney.TorNet import Node
from . import relay_v6_tmpl


def format(n: Node) -> str:
    return f"""\
{relay_v6_tmpl.format(n)}
"""
