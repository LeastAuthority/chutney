from chutney.Templating import Template
from chutney.TorNet import TorEnviron


def format(env: TorEnviron) -> str:
    t = Template(
        """\
${include:bridge.tmpl}

ServerTransportPlugin obfs4 exec ${path:obfs4proxy}
ExtOrPort $extorport
ServerTransportListenAddr obfs4 ${ip}:${ptport}

"""
    )
    return t.format(env)
