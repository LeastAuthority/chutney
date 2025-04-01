# [pep 0536](https://peps.python.org/pep-0563/) - Lazy annotation eval via
# stringification.
from __future__ import annotations

import os
import textwrap

from typing_extensions import override
from typing import Optional

import chutney.TorNet as TorNet

from chutney.errors import (
    ChutneyError,
    ChutneyInternalError,
)
from chutney.Util import mkdir_p


class LocalArtiNodeBuilder(TorNet.NodeBuilder):
    def __init__(self, node: TorNet.Node):
        TorNet.NodeBuilder.__init__(self)
        self._node = node

    def _gen_config_str(self, net: TorNet.Network) -> str:
        if not self._node._config.client:
            raise ChutneyInternalError("Arti non-client unimplemented")
        if self._node._config.exit:
            raise ChutneyInternalError("Arti exit unimplemented")
        if self._node._config.authority:
            raise ChutneyInternalError("Arti authority unimplemented")
        if self._node._config.relay:
            raise ChutneyInternalError("Arti relay unimplemented")
        if self._node._config.bridge:
            raise ChutneyInternalError("Arti bridge unimplemented")
        if self._node._config.pt_bridge:
            raise ChutneyInternalError("Arti pt_bridge unimplemented")
        arti_fallback_lines = []
        arti_auth_lines = []
        for auth in net.authorities:
            if not auth.alt_dir_auth:
                # We only configure dir auths, not bridge auths.
                # TODO: configure bridge auths too, once arti supports them.
                continue

            addrs = '"%s:%s"' % (auth.ipv4, auth.orport)
            if auth.ipv6.is_some():
                addrs += ', "%s:%s"' % (
                    auth.ipv6.unwrap(),
                    auth.orport,
                )
            arti_fallback_lines.append(
                "    {"
                + f'rsa_identity = "{auth.fingerprint.replace(" ", "")}"'
                + f', ed_identity = "{auth.fingerprint_ed25519}"'
                + f", orports = [{addrs}]"
                + "},\n"
            )
            arti_auth_lines.append(
                "    {"
                + f'name = "{auth.nick}"'
                + f', v3ident = "{auth.v3id}"'
                + "},\n"
            )
        res = textwrap.dedent(
            f"""
            [storage]
            cache_dir = "{self._node.dir}/cache"
            state_dir = "{self._node.dir}/state"

            [path_rules]
            # These values disable enforce_distance entirely; we can replace them
            # with something like Tor's "EnforceDistinctSubnets 0" if Arti ever
            # implements it.
            ipv4_subnet_family_prefix = 33
            ipv6_subnet_family_prefix = 129

            [address_filter]
            # Allow the client to accept requests to connect to e.g. 127.0.0.1
            allow_local_addrs = true
            """
        )
        res += textwrap.dedent(
            """
            [tor_network]
            fallback_caches = [
            """
        )
        res += "".join(arti_fallback_lines)
        res += "]\n"
        res += "authorities = [\n"
        res += "".join(arti_auth_lines)
        res += "]\n"

        if self._node._config.bridgeclient:
            res += textwrap.dedent(
                """
                [bridges]
                enabled = "auto"
                bridges = '''
                """
            )
            for bd in net.bridges:
                bridgeline: str
                if bd.pt_transport.is_some():
                    bridgeline = "{transport} {ip}:{port} {fp} {pt_extra}\n".format(
                        transport=bd.pt_transport.unwrap(),
                        ip=bd.ipaddr,
                        port=bd.port,
                        fp=bd.fingerprint,
                        pt_extra=bd.pt_extra.unwrap_or_raise(
                            ChutneyError("Missing pt_extra")
                        ),
                    )
                else:
                    bridgeline = "{ip}:{port} {fp}\n".format(
                        ip=bd.ipaddr,
                        port=bd.port,
                        fp=bd.fingerprint,
                    )
                res += bridgeline
            res += "'''\n"
        return res

    @override
    def checkConfig(self, net: TorNet.Network) -> None:
        self._gen_config_str(net)

    @override
    def preConfig(self, net: TorNet.Network) -> None:
        pass

    @override
    def config(self, net: TorNet.Network) -> None:
        config_str = self._gen_config_str(net)
        mkdir_p(self._node.dir)
        with open(os.path.join(self._node.dir, self._node.torrc_fname), "w") as f:
            f.write(config_str)

    @override
    def postConfig(self, net: TorNet.Network) -> None:
        pass

    @override
    def isSupported(self, net: TorNet.Network) -> bool:
        # We don't implement any arti feature-probing yet
        return True

    @override
    def getAltAuthLines(
        self, hasbridgeauth: bool = False
    ) -> Optional[TorNet.AuthorityLine]:
        if self._node._config.authority:
            raise ChutneyInternalError("arti authorities unimplemented")
        return None

    @override
    def getBridgeLines(self) -> list[TorNet.BridgeLine]:
        if self._node._config.bridge:
            raise ChutneyInternalError("arti bridges unimplemented")
        return []
