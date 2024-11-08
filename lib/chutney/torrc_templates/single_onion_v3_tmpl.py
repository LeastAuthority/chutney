from chutney.TorNet import TorEnviron
from . import single_onion_common_i


def format(env: TorEnviron) -> str:
    return f"""\
{single_onion_common_i.format(env)}
HiddenServiceVersion 3
"""
