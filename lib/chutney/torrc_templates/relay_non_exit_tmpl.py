from chutney.TorNet import TorEnviron
from . import relay_non_dir_tmpl


def format(env: TorEnviron) -> str:
    return f"""\
{relay_non_dir_tmpl.format(env)}
DirPort {env.dirport}
"""
