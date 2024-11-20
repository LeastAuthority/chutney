import re

from chutney.TorNet import Node
from . import exit_v6_i, relay_non_exit_tmpl

# This file is named "relay.tmpl" for compatibility with previous
# chutney versions

# An exit relay that can exit to IPv4 & IPv6 localhost
# (newer versions of tor need this to be explicitly configured)


def format(n: Node) -> str:
    res = f"""\
{relay_non_exit_tmpl.format(n)}
{exit_v6_i.format(n)}
"""
    assert re.search(r"^ExitPolicy accept 127.0.0.0/8:*", res, flags=re.MULTILINE), res
    return res
