from chutney.TorNet import TorEnviron
from . import client_only_v6_md_i, single_onion_tmpl


def format(env: TorEnviron) -> str:
    return f"""\
{single_onion_tmpl.format(env)}
# Onion services are just another kind of client
{client_only_v6_md_i.format(env)}
"""
