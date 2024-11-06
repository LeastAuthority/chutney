from chutney.Templating import Template
from chutney.TorNet import TorEnviron


def format(env: TorEnviron) -> str:
    t = Template(
        """\
# This file is a backwards-compatibility redirect
# Older chutney networks use single-onion.tmpl for v2 single onion services
${include:single-onion-v2.tmpl}
"""
    )
    return t.format(env)
