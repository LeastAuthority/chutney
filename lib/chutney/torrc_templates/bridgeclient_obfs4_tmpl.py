from chutney.TorNet import Node
from chutney.Util import find_executable_on_path
from . import bridgeclient_tmpl


def format(n: Node) -> str:
    return f"""\
{bridgeclient_tmpl.format(n)}

ClientTransportPlugin obfs4 exec {find_executable_on_path("obfs4proxy")}
"""
