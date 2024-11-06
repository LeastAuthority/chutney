from chutney.Templating import Template, Environ


def format(env: Environ) -> str:
    t = Template(
        """\
${include:common.i}
SocksPort 0
Address $ip

HiddenServiceDir ${dir}/hidden_service

# Redirect requests to the port used by chutney verify
HiddenServicePort 5858 127.0.0.1:4747
"""
    )
    return t.format(env)
