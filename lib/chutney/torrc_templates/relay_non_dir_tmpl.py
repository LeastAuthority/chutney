from chutney.TorNet import Node
from . import common_i


def format(n: Node) -> str:
    return f"""\
{common_i.format(n)}
SocksPort 0
OrPort {n.orport}{" IPv4Only" if n._config.disableipv6 else ""}
Address {n._config.ip}

# Must be included before exit-v{{4,6}}.i
ExitRelay 0

# These options are set here so they apply to IPv4 and IPv6 Exits
#
# Tell Exits to avoid using DNS: otherwise, chutney will fail if DNS fails
# (Chutney only accesses 127.0.0.1 and ::1, so it doesn't need DNS)
ServerDNSDetectHijacking 0
ServerDNSTestAddresses
# If this option is /dev/null, or any other empty or unreadable file, tor exits
# will not use DNS. Otherwise, DNS is enabled with this config.
# (If the following line is commented out, tor uses /etc/resolv.conf.)
{n._config.server_dns_resolv_conf}
"""
