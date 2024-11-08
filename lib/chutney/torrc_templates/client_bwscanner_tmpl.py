from chutney.TorNet import TorEnviron
from . import common_i


def format(env: TorEnviron) -> str:
    return f"""\
{common_i.format(env)}
SocksPort {env.socksport}
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
