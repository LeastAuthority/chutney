from chutney.TorNet import TorEnviron
from . import bridge_tmpl, orport_v6_i


def format(env: TorEnviron) -> str:
    return f"""\
{bridge_tmpl.format(env)}

# A bridge that has an IPv6 ORPort
{orport_v6_i.format(env)}
"""
