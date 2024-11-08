from chutney.TorNet import TorEnviron
from . import client_tmpl


def format(env: TorEnviron) -> str:
    return f"""\
{client_tmpl.format(env)}

UseBridges 1

# In some tor versions, Microdescriptors don't work well with bridge clients
# But the latest git sources appear to be fine
#UseMicrodescriptors 0

{env.network.bridges}
"""
