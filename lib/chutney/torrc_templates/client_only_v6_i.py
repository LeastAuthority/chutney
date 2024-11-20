from chutney.TorNet import Node


def format(n: Node) -> str:
    return """\
# Due to Tor bug #19608, microdescriptors can't be used by IPv6-only clients
# running tor 0.2.9 and earlier
UseMicrodescriptors 0
"""
