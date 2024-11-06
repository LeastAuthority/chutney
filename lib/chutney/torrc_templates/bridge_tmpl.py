from chutney.Templating import Template, Environ


def format(env: Environ) -> str:
    t = Template(
        """\
${include:relay-non-dir.tmpl}

BridgeRelay 1
# Bridges don't have a DirPort
DirPort 0
# Nor do we have GEOIP files in any reliable location
BridgeRecordUsageByCountry 0
"""
    )
    return t.format(env)
