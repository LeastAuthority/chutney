from chutney.TorNet import NodeConfig
from . import relay_non_exit_tmpl


def format(n: NodeConfig) -> str:
    return f"""\
{relay_non_exit_tmpl.format(n)}

Nickname relay1mbyteMAB
MaxAdvertisedBandwidth 1 MBytes
"""
