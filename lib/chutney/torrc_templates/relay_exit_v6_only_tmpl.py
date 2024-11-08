from chutney.TorNet import TorEnviron
from . import relay_v6_tmpl


def format(env: TorEnviron) -> str:
    return f"""\
{relay_v6_tmpl.format(env)}
"""
