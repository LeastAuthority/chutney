from chutney.Templating import Template
from chutney.TorNet import TorEnviron


def format(env: TorEnviron) -> str:
    t = Template(
        """\
${include:authority.tmpl}

# An authority that has an IPv6 ORPort
${include:orport-v6.i}

# And has IPv6 connectivity
AuthDirHasIPv6Connectivity 1
"""
    )
    return t.format(env)
