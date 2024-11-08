from chutney.TorNet import TorEnviron
from . import relay_non_exit_tmpl


def format(env: TorEnviron) -> str:
    return f"""\
{relay_non_exit_tmpl.format(env)}

Nickname relay1mbyteMAB
MaxAdvertisedBandwidth 1 MBytes
"""
