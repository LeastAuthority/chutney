from chutney.TorNet import TorEnviron
from . import common_i


def format(env: TorEnviron) -> str:
    return f"""\
{common_i.format(env)}
SocksPort 0
Address {env.ip}

HiddenServiceDir {env.dir}/hidden_service

# Redirect requests to the port used by chutney verify
HiddenServicePort 5858 127.0.0.1:4747
"""
