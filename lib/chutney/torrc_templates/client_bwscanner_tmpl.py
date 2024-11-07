from chutney.TorNet import Node
from . import common_i


def format(n: Node) -> str:
    return f"""\
{common_i.format(n)}
SocksPort {n._config.socksport}
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
