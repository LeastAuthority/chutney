from chutney.TorNet import TorEnviron
from . import authority_tmpl, orport_v6_i


def format(env: TorEnviron) -> str:
    return f"""\
{authority_tmpl.format(env)}

# An authority that has an IPv6 ORPort
{orport_v6_i.format(env)}

# And has IPv6 connectivity
AuthDirHasIPv6Connectivity 1
"""
