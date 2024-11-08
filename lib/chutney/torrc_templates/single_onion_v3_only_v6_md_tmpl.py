from chutney.TorNet import TorEnviron
from . import single_onion_v3_tmpl, client_only_v6_md_i


def format(env: TorEnviron) -> str:
    return f"""\
{single_onion_v3_tmpl.format(env)}
# Onion services are just another kind of client
{client_only_v6_md_i.format(env)}
"""
