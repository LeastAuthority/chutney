from chutney.TorNet import TorEnviron
from . import common_i


def format(env: TorEnviron) -> str:
    return f"""\
{common_i.format(env)}
SocksPort {env.socksport}
"""
