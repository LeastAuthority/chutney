import textwrap

from chutney.TorNet import Node, ChutneyError, V3_AUTH_VOTING_INTERVAL


def format(n: Node) -> str:
    res = textwrap.dedent(
        f"""
        TestingTorNetwork 1

        ## Rapid Bootstrap Testing Options ##
        # These typically launch a working minimal Tor network in ~20s
        # These parameters make tor networks bootstrap fast,
        # but can cause consensus instability and network unreliability
        # (Some are also bad for security.)
        #
        # We need at least 3 descriptors to build circuits.
        # In a 3 relay network, 0.67 > 2/3, so we try hard to get 3 descriptors.
        # In larger networks, 0.67 > 2/N, so we try hard to get >=3 descriptors.
        PathsNeededToBuildCircuits 0.67
        TestingDirAuthVoteExit *
        TestingDirAuthVoteHSDir *
        V3AuthNIntervalsValid 2

        ## Always On Testing Options ##
        # We enable TestingDirAuthVoteGuard to avoid Guard stability requirements
        TestingDirAuthVoteGuard *
        # We set TestingMinExitFlagThreshold to 0 to avoid Exit bandwidth requirements
        TestingMinExitFlagThreshold 0
        # VoteOnHidServDirectoriesV2 needs to be set for HSDirs to get the HSDir flag
        #Default VoteOnHidServDirectoriesV2 1

        ## Options that we always want to test ##
        DataDirectory {n.dir}
        RunAsDaemon 1
        ConnLimit {n._config.connlimit}
        Nickname {n.nick}
        # Let tor close connections gracefully before exiting
        ShutdownWaitLength 2
        DisableDebuggerAttachment 0

        AddressDisableIPv6 {int(n._config.disableipv6)}
        ControlPort {n.controlport}
        # Use ControlSocket rather than ControlPort unix: to support older tors
        ControlSocket {n.controlsocket or 0}
        CookieAuthentication 1
        PidFile {n.dir}/pid

        Log notice file {n.dir}/notice.log
        Log info file {n.dir}/info.log
        # Turn this off to save space
        #Log debug file {n.dir}/debug.log
        ProtocolWarnings 1
        SafeLogging 0
        LogTimeGranularity 1

        # Options that we can disable at runtime, based on n vars

        # Use tor's sandbox. Defaults to 1 on Linux, and 0 on other platforms.
        # Use CHUTNEY_TOR_SANDBOX=0 to disable, if tor's sandbox doesn't work with
        # your glibc.
        Sandbox {int(n._config.sandbox)}

        # Ask all child tor processes to exit when chutney's test-network.sh exits
        # (if the CHUTNEY_*_TIME options leave the network running, this option is
        # disabled)
        {n._config.owning_controller_process}

        SocksPort {n.socksport.unwrap_or(0)}

        UseMicrodescriptors {int(n._config.use_microdescriptors)}
        """
    )
    if n._config.ip.is_none():
        if n._config.disableipv6:
            raise ChutneyError("No ipv4 address and ipv6 disabled")
        if not n._config.client and not n._config.hs:
            raise ChutneyError("No ipv4 address for non-client, non-hs")
        res += "ClientUseIPv4 0\n"
    # `authorities` contains multiple lines, which breaks dedent if we include
    # it inline above.
    # TODO: `authorities` shouldn't be "pre-rendered" text.
    res += f"{n._network.authorities.strip()}\n"
    if n._config.relay:
        ipv4 = n._config.ip.unwrap_or_raise(
            ChutneyError("ipv4 address is mandatory for relays")
        )
        res += textwrap.dedent(
            f"""
            OrPort {n.orport}{" IPv4Only" if n._config.disableipv6 else ""}
            Address {ipv4}

            ExitRelay {int(n._config.exit)}

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

            DirPort {n.dirport.unwrap_or(0)}
            """
        )
    if n._config.exit:
        if not n._config.relay:
            raise ChutneyError("'exit' set without 'relay'")
        res += textwrap.dedent(
            """
            # 1. Allow exiting to IPv4 localhost and private networks by default
            # -------------------------------------------------------------

            # Each IPv4 tor instance is configured with Address 127.0.0.1 by default
            ExitPolicy accept 127.0.0.0/8:*

            # If you only want tor to connect to localhost, disable these lines:
            # This may cause network failures in some circumstances
            ExitPolicyRejectPrivate 0
            ExitPolicy accept private:*

            # 2. Optionally: Allow exiting to the entire IPv4 internet on HTTP(S)
            # -------------------------------------------------------------------

            # 2. or 3. are required to work around #11264 with microdescriptors enabled
            # "The core of this issue appears to be that the Exit flag code is
            #  optimistic (just needs a /8 and 2 ports), but the microdescriptor
            #  exit policy summary code is pessimistic (needs the entire internet)."
            # An alternative is to disable microdescriptors and use regular
            # descriptors, as they do not suffer from this issue.
            #ExitPolicy accept *:80
            #ExitPolicy accept *:443

            # 3. Optionally: Accept all IPv4 addresses, that is, the public internet
            # ----------------------------------------------------------------------
            ExitPolicy accept *:*

            # 4. Finally, reject all IPv4 addresses which haven't been permitted
            # ------------------------------------------------------------------
            ExitPolicy reject *:*
            """
        )
    if n._config.relay and n._config.ipv6_addr.is_some():
        # TODO: Avoid potential redundancy/conflict with OrPort emitted above.
        res += textwrap.dedent(
            f"""
            # Tor uses the first IPv6 ORPort address as its IPv6 address
            OrPort {n._config.ipv6_addr.unwrap()}:{n.orport} IPv6Only
            """
        )
    if n._config.exit and n._config.ipv6_addr.is_some():
        if not n._config.relay:
            raise ChutneyError(f"'exit' set without 'relay' in node {n.nick}")
        res += textwrap.dedent(
            """
            # 1. Allow exiting to IPv6 localhost and private networks by default
            # ------------------------------------------------------------------
            IPv6Exit 1

            # Each IPv6 tor instance is configured with Address [::1] by default
            # This currently only applies to bridges
            ExitPolicy accept6 [::1]:*

            # If you only want tor to connect to localhost, disable these lines:
            # This may cause network failures in some circumstances
            ExitPolicyRejectPrivate 0
            ExitPolicy accept6 private:*

            # 2. Optionally: Accept all IPv6 addresses, that is, the public internet
            # ----------------------------------------------------------------------
            # ExitPolicy accept6 *:*

            # 3. Finally, reject all IPv6 addresses which haven't been permitted
            # ------------------------------------------------------------------
            ExitPolicy reject6 *:*
            """
        )
    if n._config.authority:
        res += textwrap.dedent(
            f"""
            AuthoritativeDirectory 1
            ContactInfo auth{n.nodenum}@test.test
            """
        )
    if n._config.authority and not n._config.bridgeauthority:
        res += textwrap.dedent(
            f"""
            V3AuthoritativeDirectory 1

            # Disable authority to relay/bridge reachability checks
            # These checks happen every half hour, even in testing networks
            # As of tor 0.4.3, there is no way to speed up these checks
            AssumeReachable 1

            # Speed up the consensus cycle as fast as it will go.
            # If clock desynchronisation is an issue, increase these voting times.

            # V3AuthVotingInterval and TestingV3AuthInitialVotingInterval can be:
            #   10, 12, 15, 18, 20, ...
            # TestingV3AuthInitialVotingInterval can also be:
            #    5, 6, 8, 9
            # They both need to evenly divide 24 hours.

            # Initial Vote + Initial Dist must be less than Initial Interval
            #
            # Mixed 0.3.3 and 0.3.4 networks are unstable, due to timing changes.
            # When all 0.3.3 and earlier versions are obsolete, we may be able to revert to
            # TestingV3AuthInitialVotingInterval 5
            TestingV3AuthInitialVotingInterval 20
            TestingV3AuthInitialVoteDelay 4
            TestingV3AuthInitialDistDelay 4
            # Vote + Dist must be less than Interval/2, because when there's no consensus,
            # tor uses Interval/2 as the voting interval
            #
            V3AuthVotingInterval {V3_AUTH_VOTING_INTERVAL}
            V3AuthVoteDelay 4
            V3AuthDistDelay 4

            ConsensusParams cc_alg=2
            """
        )
    if n._config.bridgeauthority:
        if not n._config.authority:
            raise ChutneyError(
                f"'bridgeauthority' set without 'authority' in node {n.nick}"
            )
        res += "BridgeAuthoritativeDir 1\n"

    return res
