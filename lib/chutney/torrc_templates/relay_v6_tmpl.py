from chutney.TorNet import TorEnviron
from . import exit_v4_i, exit_v6_i, relay_non_exit_tmpl


def format(env: TorEnviron) -> str:
    return f"""\
{relay_non_exit_tmpl.format(env)}

# This file is named "relay.tmpl" for compatibility with previous
# chutney versions

# An exit relay that can exit to IPv4 & IPv6 localhost
# (newer versions of tor need this to be explicitly configured)

{exit_v4_i.format(env)}
{exit_v6_i.format(env)}
"""
