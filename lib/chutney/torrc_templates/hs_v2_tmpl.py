from chutney.Templating import Template
from chutney.TorNet import TorEnviron


def format(env: TorEnviron) -> str:
    t = Template(
        """\
${include:hs-common.i}

# Tor 0.3.4 and earlier default to 2, but 0.3.5 and later default to 3
HiddenServiceVersion 2
"""
    )
    return t.format(env)
