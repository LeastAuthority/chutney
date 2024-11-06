from chutney.Templating import Template
from chutney.TorNet import TorEnviron


def format(env: TorEnviron) -> str:
    t = Template(
        """\
${include:single-onion-common.i}
HiddenServiceVersion 2
"""
    )
    return t.format(env)
