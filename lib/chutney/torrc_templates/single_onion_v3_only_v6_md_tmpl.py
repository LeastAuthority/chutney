from chutney.TorNet import Node
from . import single_onion_v3_tmpl, client_only_v6_md_i


def format(n: Node) -> str:
    return f"""\
{single_onion_v3_tmpl.format(n)}
# Onion services are just another kind of client
{client_only_v6_md_i.format(n)}
"""
