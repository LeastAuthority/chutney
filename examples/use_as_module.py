#!/usr/bin/env python3
"""
Attempt to use chutney as a module.
"""

import os

from chutney import TorNet
from chutney.TorNet import Node, TorEnviron
from chutney.network_tests import verify

env = TorEnviron(controlling_pid=os.getpid())
network = TorNet.Network(env)

Authority = Node(network, tag="a", authority=1, relay=1, torrc="authority.tmpl")
ExitRelay = Node(network, tag="r", relay=1, exit=1, torrc="relay.tmpl")
Client = Node(network, tag="c", client=1, torrc="client.tmpl")

network.addNodes(Authority.getN(4) + ExitRelay.getN(1) + Client.getN(1))

network.configure()
assert(network.start())

# This has a tendency to timeout with the default of 60s.
# This timeout can be increased through the CHUTNEY_START_TIME env variable.
# TODO: Make this directly overridable from python.
network.wait_for_bootstrap()

assert(verify.run_test(network))
network.stop()
