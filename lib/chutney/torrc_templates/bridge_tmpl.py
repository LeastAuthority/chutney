from chutney.TorNet import TorEnviron
from . import relay_non_dir_tmpl


def format(env: TorEnviron) -> str:
    return f"""\
{relay_non_dir_tmpl.format(env)}

BridgeRelay 1
# Bridges don't have a DirPort
DirPort 0
# Nor do we have GEOIP files in any reliable location
BridgeRecordUsageByCountry 0
"""
