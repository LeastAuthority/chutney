#!/usr/bin/env python3
"""
Attempt to use chutney as a module.
"""

import os

from chutney import TorNet
from chutney.TorNet import NodeConfig
from chutney.network_tests import verify

network = TorNet.Network()

base = NodeConfig(controlling_pid=os.getpid())
Authority = base.specialize(tag="a", authority=1, relay=1, torrc="authority.tmpl")
ExitRelay = base.specialize(tag="r", relay=1, exit=1, torrc="relay.tmpl")
Client = base.specialize(tag="c", client=1, torrc="client.tmpl")
# TODO: Drop the 'torrc' parameters, which are no longer required.
# Keeping them in the MR that removes the need for it, to keep the validatation
# they currently enable that the generated torrc is consistent with the legacy
# template name.

network.addNodes(Authority.getN(4) + ExitRelay.getN(1) + Client.getN(1))

network.configure()
network.start()

# This has a tendency to timeout with the default of 60s.
network.wait_for_bootstrap(300)

verify.run_test(network)
network.stop()
