#!/usr/bin/env python3
"""
Attempt to use chutney as a module.
"""

import os
# XXX: make this a parameter again
os.environ["CHUTNEY_CONTROLLING_PID"] = str(os.getpid())

from chutney import TorNet
from chutney.TorNet import Node
from chutney.network_tests import verify

network = TorNet.Network()

Authority = Node(network, tag="a", authority=1, relay=1, torrc="authority.tmpl")
ExitRelay = Node(network, tag="r", relay=1, exit=1, torrc="relay.tmpl")
Client = Node(network, tag="c", client=1, torrc="client.tmpl")

network.addNodes(Authority.getN(4) + ExitRelay.getN(1) + Client.getN(1))

network.configure()
network.start()

# This has a tendency to timeout with the default of 60s.
network.wait_for_bootstrap(300)

verify.run_test(network)
network.stop()
