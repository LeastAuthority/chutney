from chutney.TorNet import TorEnviron
from . import relay_non_exit_tmpl, orport_v6_i


def format(env: TorEnviron) -> str:
    return f"""\
{relay_non_exit_tmpl.format(env)}

# A relay that has an IPv6 ORPort
{orport_v6_i.format(env)}
"""
