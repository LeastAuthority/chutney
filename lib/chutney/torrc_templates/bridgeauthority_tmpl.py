from chutney.TorNet import TorEnviron
from . import relay_non_exit_tmpl, bridgeauthority_i


def format(env: TorEnviron) -> str:
    return f"""\
{relay_non_exit_tmpl.format(env)}
{bridgeauthority_i.format(env)}
"""
