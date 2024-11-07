from chutney.TorNet import NodeConfig
from . import relay_non_exit_tmpl, exit_v4_i


def format(n: NodeConfig) -> str:
    return f"""\
{relay_non_exit_tmpl.format(n)}

# This file is named "relay.tmpl" for compatibility with previous
# chutney versions

# An exit relay that can exit to IPv4 localhost
# (newer versions of tor need this to be explicitly configured)

{exit_v4_i.format(n)}
"""
