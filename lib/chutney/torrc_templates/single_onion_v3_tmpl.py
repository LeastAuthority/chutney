from chutney.TorNet import Node
from . import single_onion_common_i


def format(n: Node) -> str:
    return f"""\
{single_onion_common_i.format(n)}
HiddenServiceVersion 3
"""
