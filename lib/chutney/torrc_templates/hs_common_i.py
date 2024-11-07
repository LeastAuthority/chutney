from chutney.TorNet import Node
from . import common_i


def format(n: Node) -> str:
    return f"""\
{common_i.format(n)}
SocksPort 0
Address {n._config.ip}

HiddenServiceDir {n._config.dir}/hidden_service

# Redirect requests to the port used by chutney verify
HiddenServicePort 5858 127.0.0.1:4747
"""
