import re

from chutney.TorNet import Node
from . import relay_non_dir_tmpl


def format(n: Node) -> str:
    res = f"""\
{relay_non_dir_tmpl.format(n)}

BridgeRelay 1
# Nor do we have GEOIP files in any reliable location
BridgeRecordUsageByCountry 0
"""
    assert re.search(r"^DirPort 0", res, flags=re.MULTILINE), res
    return res
