from chutney.TorNet import Node, ChutneyError
from chutney.Util import find_executable_on_path
from . import bridge_tmpl


def format(n: Node) -> str:
    ipv4 = n._config.ip.unwrap_or_raise(ChutneyError("ipv4 is mandatory for bridges"))
    return f"""\
{bridge_tmpl.format(n)}

ServerTransportPlugin obfs4 exec {find_executable_on_path("obfs4proxy")}
ExtOrPort {n.extorport}
ServerTransportListenAddr obfs4 {ipv4}:{n.ptport}
"""
