from chutney.Templating import Template
from chutney.TorNet import TorEnviron


def format(env: TorEnviron) -> str:
    t = Template(
        """\
# This file is a backwards-compatibility redirect
# Older chutney networks use hs.tmpl for v2 onion services
${include:hs-v2.tmpl}
"""
    )
    return t.format(env)
