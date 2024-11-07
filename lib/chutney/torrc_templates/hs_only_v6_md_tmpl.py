from chutney.TorNet import Node
from . import hs_tmpl, client_only_v6_md_i


def format(n: Node) -> str:
    return f"""\
{hs_tmpl.format(n)}
# Hidden services are just another kind of client
{client_only_v6_md_i.format(n)}
"""
