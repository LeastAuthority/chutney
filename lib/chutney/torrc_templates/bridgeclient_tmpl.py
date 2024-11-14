from chutney.TorNet import Node
from . import client_tmpl


def format(n: Node) -> str:
    return f"""\
{client_tmpl.format(n)}

UseBridges 1

# In some tor versions, Microdescriptors don't work well with bridge clients
# But the latest git sources appear to be fine
#UseMicrodescriptors 0

{n._network.bridges}
"""
