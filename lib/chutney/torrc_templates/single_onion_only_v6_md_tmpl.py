from chutney.TorNet import Node
from . import client_only_v6_md_i, single_onion_tmpl


def format(n: Node) -> str:
    return f"""\
{single_onion_tmpl.format(n)}
# Onion services are just another kind of client
{client_only_v6_md_i.format(n)}
"""
