from chutney.TorNet import NodeConfig
from . import relay_non_dir_tmpl


def format(n: NodeConfig) -> str:
    return f"""\
{relay_non_dir_tmpl.format(n)}
DirPort {n.dirport}
"""
