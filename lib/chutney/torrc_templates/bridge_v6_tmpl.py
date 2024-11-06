from chutney.Templating import Template
from chutney.TorNet import TorEnviron


def format(env: TorEnviron) -> str:
    t = Template(
        """\
${include:bridge.tmpl}

# A bridge that has an IPv6 ORPort
${include:orport-v6.i}
"""
    )
    return t.format(env)
