from chutney.TorNet import TorEnviron
from . import hs_v3_tmpl, client_only_v6_i


def format(env: TorEnviron) -> str:
    return f"""\
{hs_v3_tmpl.format(env)}
# Hidden services are just another kind of client
{client_only_v6_i.format(env)}
"""
