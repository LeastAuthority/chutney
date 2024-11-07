from chutney.TorNet import NodeConfig
from . import relay_non_dir_tmpl


def format(n: NodeConfig) -> str:
    return f"""\
{relay_non_dir_tmpl.format(n)}

BridgeRelay 1
# Bridges don't have a DirPort
DirPort 0
# Nor do we have GEOIP files in any reliable location
BridgeRecordUsageByCountry 0
"""
