from chutney.TorNet import NodeConfig
from chutney.Util import find_on_path
from . import bridge_tmpl


def format(n: NodeConfig) -> str:
    return f"""\
{bridge_tmpl.format(n)}

ServerTransportPlugin obfs4 exec {find_on_path("obfs4proxy")}
ExtOrPort {n.extorport}
ServerTransportListenAddr obfs4 {n.ip}:{n.ptport}
"""
