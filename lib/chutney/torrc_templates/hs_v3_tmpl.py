from chutney.TorNet import TorEnviron
from . import hs_common_i


def format(env: TorEnviron) -> str:
    return f"""\
{hs_common_i.format(env)}

# Tor 0.3.4 and earlier default to 2, but 0.3.5 and later default to 3
HiddenServiceVersion 3
"""
