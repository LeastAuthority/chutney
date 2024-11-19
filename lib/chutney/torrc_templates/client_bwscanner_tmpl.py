import re
from chutney.TorNet import Node
from . import common_i


def format(n: Node) -> str:
    res = f"""\
{common_i.format(n)}
UseEntryGuards 0
UseMicroDescriptors 0
FetchDirInfoEarly 1
FetchDirInfoExtraEarly 1
FetchUselessDescriptors 1
LearnCircuitBuildTimeout 0
CircuitBuildTimeout 60
ConnectionPadding 0
__DisablePredictedCircuits 1
__LeaveStreamsUnattached 1
"""
    # XXX Replace with a friendlier error message.
    # (Done at end of this MR; This XXX comment has been patched back into the
    # first commit in the MR adding this style of assertion, but not all of the
    # similar assertions added in all of the other commits.)
    assert re.search(r"^SocksPort [1-9]", res, flags=re.MULTILINE), res
    return res
