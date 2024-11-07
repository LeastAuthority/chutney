from chutney.TorNet import NodeConfig
from . import common_i


def format(n: NodeConfig) -> str:
    return f"""\
{common_i.format(n)}
SocksPort 0
Address {n.ip}

HiddenServiceDir {n.dir}/hidden_service

# Redirect requests to the port used by chutney verify
HiddenServicePort 5858 127.0.0.1:4747
"""
