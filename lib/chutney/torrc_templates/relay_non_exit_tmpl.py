from chutney.TorNet import Node
from . import relay_non_dir_tmpl


def format(n: Node) -> str:
    return f"""\
{relay_non_dir_tmpl.format(n)}
DirPort {n.dirport}
"""
