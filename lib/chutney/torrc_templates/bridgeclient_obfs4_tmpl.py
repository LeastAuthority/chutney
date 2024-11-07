from chutney.TorNet import NodeConfig
from chutney.Util import find_on_path
from . import bridgeclient_tmpl


def format(n: NodeConfig) -> str:
    return f"""\
{bridgeclient_tmpl.format(n)}

ClientTransportPlugin obfs4 exec {find_on_path("obfs4proxy")}
"""
