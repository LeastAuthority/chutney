from chutney.TorNet import TorEnviron
from . import hs_v2_tmpl


def format(env: TorEnviron) -> str:
    return f"""\
# This file is a backwards-compatibility redirect
# Older chutney networks use hs.tmpl for v2 onion services
{hs_v2_tmpl.format(env)}
"""
