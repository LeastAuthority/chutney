from chutney.TorNet import TorEnviron
from chutney.Util import find_on_path
from . import bridge_tmpl


def format(env: TorEnviron) -> str:
    return f"""\
{bridge_tmpl.format(env)}

ServerTransportPlugin obfs4 exec {find_on_path("obfs4proxy")}
ExtOrPort {env.extorport}
ServerTransportListenAddr obfs4 {env.ip}:{env.ptport}
"""
