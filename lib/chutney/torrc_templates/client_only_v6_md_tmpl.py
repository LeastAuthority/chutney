from chutney.TorNet import TorEnviron
from . import client_tmpl, client_only_v6_md_i


def format(env: TorEnviron) -> str:
    return f"""\
{client_tmpl.format(env)}
{client_only_v6_md_i.format(env)}
"""
