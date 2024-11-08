from chutney.TorNet import TorEnviron
from . import hs_tmpl, client_only_v6_md_i


def format(env: TorEnviron) -> str:
    return f"""\
{hs_tmpl.format(env)}
# Hidden services are just another kind of client
{client_only_v6_md_i.format(env)}
"""
