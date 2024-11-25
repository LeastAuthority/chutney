from chutney.TorNet import Node
from . import relay_non_exit_tmpl

# This file is named "relay.tmpl" for compatibility with previous
# chutney versions


def format(n: Node) -> str:
    res = relay_non_exit_tmpl.format(n)
    n._check_expected_pattern(r"^ExitPolicy accept 127.0.0.0/8:\*", res)
    return res
