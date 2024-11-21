import re
from chutney.TorNet import Node
from . import common_i


def format(n: Node) -> str:
    res = common_i.format(n)
    # XXX Replace with a friendlier error message.
    # (Done at end of this MR; This XXX comment has been patched back into the
    # first commit in the MR adding this style of assertion, but not all of the
    # similar assertions added in all of the other commits.)
    assert re.search(r"^SocksPort [1-9]", res, flags=re.MULTILINE), res
    assert re.search(r"^UseEntryGuards 0", res, flags=re.MULTILINE), res
    assert re.search(r"^UseMicrodescriptors 0", res, flags=re.MULTILINE), res
    return res
