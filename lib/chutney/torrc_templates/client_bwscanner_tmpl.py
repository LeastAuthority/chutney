from chutney.Templating import Template
from chutney.TorNet import TorEnviron


def format(env: TorEnviron) -> str:
    t = Template(
        """\
${include:common.i}
SocksPort $socksport
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
    )
    return t.format(env)
