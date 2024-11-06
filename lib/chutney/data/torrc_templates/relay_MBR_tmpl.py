from chutney.Templating import Template, Environ


def format(env: Environ) -> str:
    t = Template(
        """\
${include:relay-non-exit.tmpl}

Nickname relay1mbyteMBR
RelayBandwidthRate 1 MBytes
"""
    )
    return t.format(env)
