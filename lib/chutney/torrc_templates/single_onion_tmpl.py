from chutney.TorNet import TorEnviron
from . import single_onion_v2_tmpl


def format(env: TorEnviron) -> str:
    return f"""\
# This file is a backwards-compatibility redirect
# Older chutney networks use single-onion.tmpl for v2 single onion services
{single_onion_v2_tmpl.format(env)}
"""
