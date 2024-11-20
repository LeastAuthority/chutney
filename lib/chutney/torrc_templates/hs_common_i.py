import re

from chutney.TorNet import Node
from . import common_i


def format(n: Node) -> str:
    res = f"""\
{common_i.format(n)}
Address {n._config.ip.unwrap("XXX Currently only called in ipv4 contexts")}

HiddenServiceDir {n.dir}/hidden_service

# Redirect requests to the port used by chutney verify
HiddenServicePort 5858 127.0.0.1:4747
"""
    # XXX Replace with a friendlier error message.
    # (Done at end of this MR; This XXX comment has been patched back into the
    # first commit in the MR adding this style of assertion, but not all of the
    # similar assertions added in all of the other commits.)
    assert re.search(r"^SocksPort 0", res, flags=re.MULTILINE), res
    return res
