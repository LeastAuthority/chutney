#!/usr/bin/env python3
"""
Attempt to use chutney as a module.
"""

import os

from chutney import TorNet
from chutney.TorNet import Node, TorEnviron
from chutney.network_tests import verify

env = TorEnviron(controlling_pid=os.getpid())

Authority = Node(env, tag="a", authority=1, relay=1, torrc="authority.tmpl")
ExitRelay = Node(env, tag="r", relay=1, exit=1, torrc="relay.tmpl")
Client = Node(env, tag="c", client=1, torrc="client.tmpl")

network = TorNet.createNetwork(env, Authority.getN(3) + ExitRelay.getN(5) + Client.getN(2))

network.configure()
network.start()
network.wait_for_bootstrap()
verify.run_test(network)
network.stop()
