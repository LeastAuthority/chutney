from chutney.TorNet import TorEnviron
from chutney.Util import find_on_path
from . import bridgeclient_tmpl


def format(env: TorEnviron) -> str:
    return f"""\
{bridgeclient_tmpl.format(env)}

ClientTransportPlugin obfs4 exec {find_on_path("obfs4proxy")}
"""
