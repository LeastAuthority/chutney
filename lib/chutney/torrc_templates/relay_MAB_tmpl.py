from chutney.TorNet import Node
from . import relay_non_exit_tmpl


def format(n: Node) -> str:
    return f"""\
{relay_non_exit_tmpl.format(n)}

Nickname relay1mbyteMAB
MaxAdvertisedBandwidth 1 MBytes
"""
