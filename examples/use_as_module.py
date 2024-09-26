#!/usr/bin/env python3
"""
Attempt to use chutney as a module.
"""

import os

from chutney import TorNet
from chutney.TorNet import Node

TorNet.DEFAULTS['controlling_pid'] = os.getpid()

def makeNodes():
    Authority = Node(tag="a", authority=1, relay=1, torrc="authority.tmpl")
    ExitRelay = Node(tag="r", relay=1, exit=1, torrc="relay.tmpl")
    Client = Node(tag="c", client=1, torrc="client.tmpl")
    return Authority.getN(3) + ExitRelay.getN(5) + Client.getN(2)

network = TorNet.createNetwork(makeNodes)

network.configure()
network.start()
network.wait_for_bootstrap()
network.stop()
