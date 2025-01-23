import base64
import errno
import os
import re
import signal
import time

from collections.abc import Collection
from pathlib import Path
from typeguard import check_type
from typing import Optional, Union
from typing_extensions import override

import chutney.TorNet as TorNet

from chutney.tor.util import get_tor_version
from chutney.Debug import debug
from chutney.Util import (
    launch_process,
    Option,
)


class LocalNodeController(TorNet.NodeController):

    def __init__(self, network: TorNet.Network, node: TorNet.Node):
        TorNet.NodeController.__init__(self)
        self._network = network
        self._node = node
        self.most_recent_oniondesc_status: Optional[tuple[int, str, str]] = None
        self.most_recent_bootstrap_status: Optional[tuple[int, str, str]] = None

    def _loadEd25519Id(self) -> Option[str]:
        """
        Read the ed25519 identity key for this router, encode it using
        base64, strip trailing padding, and return it.

        If the file does not exist, returns None.

        Raises a ValueError if the file appears to be corrupt.
        """
        datadir = self._node.dir
        key_file = Path(datadir, "keys", "ed25519_master_id_public_key")
        # If we're called early during bootstrap, the file won't have been
        # created yet. (And some very old tor versions don't have ed25519.)
        if not key_file.exists():
            debug(
                (
                    "File {} does not exist. Are you running a very old tor " "version?"
                ).format(key_file)
            )
            return Option(None)

        EXPECTED_ED25519_FILE_SIZE = 64
        key_file_size = key_file.stat().st_size
        if key_file_size != EXPECTED_ED25519_FILE_SIZE:
            raise ValueError(
                (
                    "The current size of the file is {} bytes, which is not"
                    "matching the expected value of {} bytes"
                ).format(key_file_size, EXPECTED_ED25519_FILE_SIZE)
            )

        with key_file.open(mode="rb") as f:
            ED25519_KEY_POSITION = 32
            f.seek(ED25519_KEY_POSITION)
            rest_file = f.read()
            encoded_value = base64.b64encode(rest_file)
            # tor strips trailing base64 padding
            ed25519_id = encoded_value.decode("utf-8").replace("=", "")
            EXPECTED_ED25519_BASE64_KEY_SIZE = 43
            key_base64_size = len(ed25519_id)
            if key_base64_size != EXPECTED_ED25519_BASE64_KEY_SIZE:
                raise ValueError(
                    (
                        "The current length of the key is {}, which is not "
                        "matching the expected length of {}"
                    ).format(key_base64_size, EXPECTED_ED25519_BASE64_KEY_SIZE)
                )
            return Option(ed25519_id)

    def _loadPtExtraObfs4(self) -> Option[str]:
        """_loadPtExtra impl for the obfs4 transport"""
        assert self._node._config.pt_transport == "obfs4"
        location = Path(self._node.dir, "pt_state", "obfs4_bridgeline.txt")
        if not location.exists():
            return Option(None)
        # read the file and find the actual line
        with open(location, "r") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                if line.isspace():
                    continue
                m = re.match(r"(.*<FINGERPRINT>) (cert.*)", line)
                if m:
                    return Option(m.group(2))
        return Option(None)

    def _loadPtExtra(self) -> Option[str]:
        """Load extra bridge info to use this node as a PT bridge.

        Returns an empty string if there is no such info (e.g. this isn't a PT bridge).
        Returns None if we *expect* there to be such info but couldn't locate it (yet).
        """
        # `match` would be nice here, but requires python 3.10.
        ptt = self._node._config.pt_transport
        if ptt == "":
            return Option("")
        elif ptt == "obfs4":
            return self._loadPtExtraObfs4()
        else:
            raise TorNet.ChutneyError("Unhandled pt_transport: " + ptt)

    @override
    def getNick(self) -> str:
        # TODO: Consider whether this method probably ought to get the "ground
        # truth" by looking at the torrc or querying the control port etc.
        return self._node.nick

    def getBridge(self) -> int:
        """Return the bridge (relay) flag for this node."""
        try:
            return check_type(self._node._config.bridge, int)
        except KeyError:
            return 0

    @override
    def getPtExtra(self) -> Option[str]:
        # TODO: cache result? I don't really think it's worth the extra complexity,
        # but not doing so is inconsistent with the other accessors.
        return self._loadPtExtra()

    def getEd25519Id(self) -> Option[str]:
        """Return the base64-encoded ed25519 public key of this node."""
        if self._node.ed25519_id.is_none():
            self._node.ed25519_id = self._loadEd25519Id()
        return self._node.ed25519_id

    def getBridgeClient(self) -> bool:
        """Return the bridge client flag for this node."""
        try:
            return bool(check_type(self._node._config.bridgeclient, Union[int, bool]))
        except KeyError:
            return False

    def getBridgeAuthority(self) -> bool:
        """Return the bridge authority flag for this node."""
        try:
            return bool(
                check_type(self._node._config.bridgeauthority, Union[int, bool])
            )
        except KeyError:
            return False

    def getAuthority(self) -> bool:
        """Return the authority flag for this node."""
        try:
            return bool(check_type(self._node._config.authority, Union[int, bool]))
        except KeyError:
            return False

    @override
    def getConsensusAuthority(self) -> bool:
        return self.getAuthority() and not self.getBridgeAuthority()

    def getConsensusMember(self) -> bool:
        """Is this node listed in the consensus?"""
        return self.getDirServer() and not self.getBridge()

    def getDirServer(self) -> bool:
        """Return the relay flag for this node.
        The relay flag is set on authorities, relays, and bridges.
        """
        try:
            return bool(check_type(self._node._config.relay, Union[int, bool]))
        except KeyError:
            return False

    def getConsensusRelay(self) -> bool:
        """Is this node published in the consensus?
        True for authorities and relays; False for bridges and clients.
        """
        return self.getDirServer() and not self.getBridge()

    # Older tor versions need extra time to bootstrap.
    # (And we're not sure exactly why -  maybe we fixed some bugs in 0.4.0?)
    #
    # This version prefix compares less than all 0.4-series, and any
    # future version series (for example, 0.5, 1.0, and 22.0)
    MIN_TOR_VERSION_FOR_TIMING_FIX = "Tor 0.4"

    def isLegacyTorVersion(self) -> bool:
        """Is the current Tor version 0.3.5 or earlier?"""
        tor = self._node._config.tor
        tor_version = get_tor_version(tor)
        min_version = LocalNodeController.MIN_TOR_VERSION_FOR_TIMING_FIX

        # We could compare the version components, but this works for now
        # (And if it's a custom Tor implementation, it shouldn't have this
        # particular timing bug.)
        if tor_version.startswith("Tor ") and tor_version < min_version:
            return True
        else:
            return False

    # The extra time after other descriptors have finished, and before
    # verifying.
    DEFAULT_WAIT_FOR_UNCHECKED_DIR_INFO = 0
    # We don't check for onion service descriptors before verifying.
    # See #33609 for details.
    HS_WAIT_FOR_UNCHECKED_DIR_INFO = TorNet.V3_AUTH_VOTING_INTERVAL + 10
    # We don't check for bridge descriptors before verifying.
    # See #33581.
    BRIDGE_WAIT_FOR_UNCHECKED_DIR_INFO = 10

    # Let everything propagate for another consensus period before verifying.
    LEGACY_WAIT_FOR_UNCHECKED_DIR_INFO = TorNet.V3_AUTH_VOTING_INTERVAL

    @override
    def getUncheckedDirInfoWaitTime(self) -> float:
        if self._node.isOnionService():
            return LocalNodeController.HS_WAIT_FOR_UNCHECKED_DIR_INFO
        elif self.getBridge():
            return LocalNodeController.BRIDGE_WAIT_FOR_UNCHECKED_DIR_INFO
        elif self.isLegacyTorVersion():
            return LocalNodeController.LEGACY_WAIT_FOR_UNCHECKED_DIR_INFO
        else:
            return LocalNodeController.DEFAULT_WAIT_FOR_UNCHECKED_DIR_INFO

    def getPid(self) -> Optional[int]:
        """Read the pidfile, and return the pid of the running process.
        Returns None if there is no pid in the file.
        """
        pidfile = Path(self._node.pidfile)
        if not pidfile.exists():
            return None

        with pidfile.open(mode="r") as f:
            try:
                return int(f.read())
            except ValueError:
                return None

    @override
    def isRunning(self) -> bool:
        pid = self.getPid()
        if pid is None:
            return False
        return self._is_running_with_pid(pid)

    def _is_running_with_pid(self, pid: int) -> bool:
        """As for isRunning, but takes the pid, which should be the process ID for this node"""
        assert pid == self.getPid()
        try:
            os.kill(pid, 0)  # "kill 0" == "are you there?"
        except OSError as e:
            if e.errno == errno.ESRCH:
                return False
            raise

        # okay, so the process exists.  Say "True" for now.
        # XXXX check if this is really tor!
        return True

    @override
    def check(self, listRunning: bool = True, listNonRunning: bool = False) -> bool:
        # XXX Split this into "check" and "print" parts.
        pid = self.getPid()
        nick = self._node.nick
        datadir = self._node.dir
        corefile = None
        if pid is not None:
            corefile = "core.%d" % pid
        tor_version = get_tor_version(self._node._config.tor)
        if pid is not None and self._is_running_with_pid(pid):
            if listRunning:
                # PIDs are typically 65535 or less
                print(
                    "{:12} is running with PID {:5}: {}".format(nick, pid, tor_version)
                )
            return True
        elif corefile and Path(datadir, corefile).exists():
            if listNonRunning:
                print(
                    "{:12} seems to have crashed, and left core file {}: {}".format(
                        nick, corefile, tor_version
                    )
                )
            return False
        else:
            if listNonRunning:
                print("{:12} is stopped: {}".format(nick, tor_version))
            return False

    @override
    def hup(self) -> bool:
        pid = self.getPid()
        nick = self._node.nick
        if pid is not None and self._is_running_with_pid(pid):
            print("Sending sighup to {}".format(nick))
            os.kill(pid, signal.SIGHUP)
            return True
        else:
            print("{:12} is not running".format(nick))
            return False

    @override
    def start(self) -> None:
        if self.isRunning():
            print("{:12} is already running".format(self._node.nick))
            return
        tor_path = self._node._config.tor
        torrc = self._node.torrc_fname
        cmdline = [
            tor_path,
            "-f",
            torrc,
        ]
        p = launch_process(cmdline)
        if self.waitOnLaunch():
            # this requires that RunAsDaemon is set.
            (stdouterr, empty_stderr) = p.communicate()
            debug(stdouterr)
            assert empty_stderr is None
            # We expect the parent process to have exited with code 0.
            if p.returncode != 0:
                raise TorNet.ChutneyError(
                    f"Couldn't launch {self._node.nick:12}"
                    + f" command '{' '.join(cmdline)}': "
                    + f" exit {p.returncode},"
                    + f" output '{stdouterr}'"
                )
        else:
            # this requires RunAsDaemon to *not* be set, and is slower.
            #
            # poll() only catches failures before the call itself
            # so let's sleep a little first
            # this does, of course, slow down process launch
            # which can require an adjustment to the voting interval
            #
            # avoid writing a newline or space when polling
            # so output comes out neatly
            print(".", end="", flush=True)
            assert self._node._config.poll_launch_time is not None
            time.sleep(self._node._config.poll_launch_time)
            p.poll()
            if p.returncode is not None:
                # Process unexpectedly exited
                raise TorNet.ChutneyError(
                    f"'{self._node.nick:12}' unexpectedly exited with code {p.returncode}."
                    + f" command '{' '.join(cmdline)}'"
                    + f" after waiting {self._node._config.poll_launch_time} seconds for launch"
                )

    @override
    def stop(self, sig: int = signal.SIGINT) -> None:
        pid = self.getPid()
        if pid is None or not self._is_running_with_pid(pid):
            print("{:12} is not running".format(self._node.nick))
            return
        os.kill(pid, sig)

    @override
    def cleanupRunFiles(self) -> None:
        # check for stale lock files when Tor crashes
        self.cleanup_lockfile()
        # move aside old pid files after Tor stops running
        self.cleanup_pidfile()

    def cleanup_lockfile(self) -> None:
        """Remove lock file if this node is no longer running."""
        lf = Path(self._node.lockfile)
        if not self.isRunning() and lf.exists():
            debug("Removing stale lock file for {} ...".format(self._node.nick))
            os.remove(lf)

    def cleanup_pidfile(self) -> None:
        """Move PID file to pidfile.old if this node is no longer running
        so that we don't try to stop the node again.
        """
        pidfile = Path(self._node.pidfile)
        if not self.isRunning() and pidfile.exists():
            debug("Renaming stale pid file for {} ...".format(self._node.nick))
            pidfile.rename(pidfile.with_suffix(".old"))

    def waitOnLaunch(self) -> bool:
        """Check whether we can wait() for the tor process to launch"""
        # TODO: is this the best place for this code?
        # RunAsDaemon default is 0
        runAsDaemon = False
        with open(self._node.torrc_fname, "r") as f:
            for line in f.readlines():
                stline = line.strip()
                # if the line isn't all whitespace or blank
                if len(stline) > 0:
                    splline = stline.split()
                    # if the line has at least two tokens on it
                    if (
                        len(splline) > 0
                        and splline[0].lower() == "RunAsDaemon".lower()
                        and splline[1] == "1"
                    ):
                        # use the RunAsDaemon value from the torrc
                        # TODO: multiple values?
                        runAsDaemon = True
        if runAsDaemon:
            # we must use wait() instead of poll()
            self._node._config.poll_launch_time = None
            return True
        else:
            # we must use poll() instead of wait()
            if self._node._config.poll_launch_time is None:
                self._node._config.poll_launch_time = (
                    self._node._config.poll_launch_time_default
                )
            return False

    def getLogfile(self, info: bool = False) -> Path:
        """Return the expected path to the logfile for this instance."""
        datadir = check_type(self._node.dir, Path)
        if info:
            logname = "info.log"
        else:
            logname = "notice.log"
        return datadir.joinpath(logname)

    def updateLastOnionServiceDescStatus(self) -> None:
        """Look through the logs and cache the last onion service
        descriptor status received.
        """
        logfname = self.getLogfile(info=True)
        if not os.path.exists(logfname):
            self.most_recent_oniondesc_status = (
                TorNet.MISSING_FILE_CODE,
                "no_logfile",
                "There is no logfile yet.",
            )
        percent = TorNet.NO_RECORDS_CODE
        keyword = "no_message"
        message = "No onion service descriptor messages yet."
        with open(logfname, "r") as f:
            for line in f:
                m_v2 = re.search(r"Launching upload for hidden service (.*)", line)
                if m_v2:
                    percent = TorNet.ONIONDESC_PUBLISHED_CODE
                    keyword = TorNet.HSV2_KEYWORD
                    message = m_v2.groups()[0]
                    break
                # else check for HSv3
                m_v3 = re.search(
                    r"Service ([^\s]+ [^\s]+ descriptor of revision .*)", line
                )
                if m_v3:
                    percent = TorNet.ONIONDESC_PUBLISHED_CODE
                    keyword = TorNet.HSV3_KEYWORD
                    message = m_v3.groups()[0]
                    break
        self.most_recent_oniondesc_status = (percent, keyword, message)

    def getLastOnionServiceDescStatus(self) -> tuple[int, str, str]:
        """Return the last onion descriptor message fetched by
        updateLastOnionServiceDescStatus as a 3-tuple of percentage
        complete, the hidden service version, and message.

        The return status depends on the last time updateLastStatus()
        was called; that function must be called before this one.
        """
        rv = self.most_recent_oniondesc_status
        # Caller is required to have set this via `updateLastStatus` first.
        # TODO: just call it ourselves if None, or use a default value?
        assert rv is not None
        return rv

    @override
    def updateLastBootstrapStatus(self) -> None:
        logfname = self.getLogfile()
        if not logfname.exists():
            self.most_recent_bootstrap_status = (
                TorNet.MISSING_FILE_CODE,
                "no_logfile",
                "There is no logfile yet.",
            )
            return
        percent = TorNet.NO_RECORDS_CODE
        keyword = "no_message"
        message = "No bootstrap messages yet."
        with logfname.open(mode="r") as f:
            for line in f:
                m = re.search(r"Bootstrapped (\d+)%(?: \(([^\)]*)\))?: (.*)", line)
                if m:
                    percent_s, keyword, message = m.groups()
                    percent = int(percent_s)
        self.most_recent_bootstrap_status = (percent, keyword, message)

    @override
    def getLastBootstrapStatus(self) -> tuple[int, str, str]:
        rv = self.most_recent_bootstrap_status
        # Caller is required to have set this via `updateLastStatus` first.
        # TODO: just call it ourselves if None, or use a default value?
        assert rv is not None
        return rv

    @override
    def updateLastStatus(self) -> None:
        self.updateLastOnionServiceDescStatus()
        self.updateLastBootstrapStatus()

    @override
    def isBootstrapped(self) -> bool:
        pct, _, _ = self.getLastBootstrapStatus()
        if pct != TorNet.SUCCESS_CODE:
            return False
        if self._node.isOnionService():
            pct, _, _ = self.getLastOnionServiceDescStatus()
            if pct != TorNet.ONIONDESC_PUBLISHED_CODE:
                return False
        return True

    @override
    def getNodeCacheDirInfoPaths(
        self, v2_dir_paths: bool
    ) -> tuple[int, int, Optional[dict[str, Path]]]:
        to_bridge_client = self.getBridgeClient()
        to_bridge_auth = self.getBridgeAuthority()
        datadir = self._node.dir
        to_dir_server = self.getDirServer()

        desc = Path(datadir, "cached-descriptors")
        desc_new = Path(datadir, "cached-descriptors.new")

        paths = None
        if v2_dir_paths:
            ns_cons = Path(datadir, "cached-consensus")
            md_cons = Path(datadir, "cached-microdesc-consensus")
            md = Path(datadir, "cached-microdescs")
            md_new = Path(datadir, "cached-microdescs.new")

            paths = {
                "ns_cons": ns_cons,
                "desc": desc,
                "desc_new": desc_new,
                "md_cons": md_cons,
                "md": md,
                "md_new": md_new,
            }
        # the published node is a bridge
        # bridges are only used by bridge clients and bridge authorities
        elif to_bridge_client or to_bridge_auth:
            # bridge descs are stored with relay descs
            paths = {"desc": desc, "desc_new": desc_new}
            if to_bridge_auth:
                br_status = Path(datadir, "networkstatus-bridges")
                paths["br_status"] = br_status
        else:
            # We're looking for bridges, but other nodes don't use bridges
            paths = None

        return (to_dir_server, to_bridge_client, paths)

    def getNodePublishedDirInfoPaths(
        self,
    ) -> Optional[dict[str, tuple[int, int, Optional[dict[str, Path]]]]]:
        """Return a dict of paths to consensus files, where we expect this
        node to be published.

        The dict keys are the nicks for each node.

        See getNodeCacheDirInfoPaths() for the path data structure, and which
        nodes appear in each type of directory.
        """
        consensus_member = self.getConsensusMember()
        bridge_member = self.getBridge()
        # Nodes can be a member of only one kind of directory
        assert not (consensus_member and bridge_member)

        # Clients don't appear in any consensus
        if not consensus_member and not bridge_member:
            return None

        launch_phase = TorNet.CUR_LAUNCH_PHASE

        # at this point, consensus_member == not bridge_member
        directory_files = dict()
        for node in self._network._nodes:
            if node._config.launch_phase > launch_phase:
                continue
            nick = check_type(node.nick, str)
            controller = node.getController()
            node_files = controller.getNodeCacheDirInfoPaths(consensus_member)
            # skip empty file lists
            if node_files:
                directory_files[nick] = node_files

        assert len(directory_files) > 0
        return directory_files

    def getNodeDirInfoStatusPattern(self, dir_format: str) -> Optional[str]:
        """Returns a regular expression pattern for finding this node's entry
        in a dir_format file. Returns None if the requested pattern is not
        available.
        """
        nickname = self.getNick()
        ed25519_key = self.getEd25519Id()

        cons = dir_format in ["ns_cons", "md_cons", "br_status"]
        desc = dir_format in ["desc", "desc_new"]
        md = dir_format in ["md", "md_new"]

        assert cons or desc or md

        if cons:
            # Disabled due to bug #33407: chutney bridge authorities don't
            # publish bridge descriptors in the bridge networkstatus file
            if dir_format == "br_status":
                return None
            else:
                # ns_cons and md_cons work
                return r"^r " + nickname + " "
        elif desc:
            return r"^router " + nickname + " "
        elif md:
            return ed25519_key.map(
                lambda s: r"^id ed25519 " + re.escape(s)
            ).as_optional()
        else:
            raise TorNet.ChutneyError(f"Invalid dir_format {dir_format}")

    def getFileDirInfoStatus(
        self, dir_format: str, dir_path: Path
    ) -> tuple[int, Collection[str], str]:
        """Check dir_path, a directory path used by another node, to see if
        this node is present. The directory path is a dir_format file.

        Returns a status 3-tuple containing:
          * an integer status code:
            * negative numbers correspond to errors,
            * NO_PROGRESS_CODE means "not in the directory", and
            * SUCCESS_CODE means "in the directory";
          * a set containing dir_format; and
          * a status message string.
        """
        if not dir_path.exists():
            return (TorNet.MISSING_FILE_CODE, {dir_format}, "No dir file")

        dir_pattern = self.getNodeDirInfoStatusPattern(dir_format)

        line_count = 0
        with dir_path.open(mode="r") as f:
            for line in f:
                line_count = line_count + 1
                if dir_pattern:
                    m = re.search(dir_pattern, line)
                    if m:
                        return (
                            TorNet.SUCCESS_CODE,
                            {dir_format},
                            "Dir info cached",
                        )

        if line_count == 0:
            return (TorNet.NO_RECORDS_CODE, {dir_format}, "Empty dir file")
        elif dir_pattern is None:
            return (
                TorNet.NOT_YET_IMPLEMENTED_CODE,
                {dir_format},
                "Not yet implemented",
            )
        elif line_count < 8:
            # The minimum size of the bridge networkstatus is 3 lines,
            # and the minimum size of one bridge is 5 lines
            # Let the user know the dir file is unexpectedly small
            return (
                TorNet.SHORT_FILE_CODE,
                {dir_format},
                "Very short dir file",
            )
        else:
            return (
                TorNet.NO_PROGRESS_CODE,
                {dir_format},
                "Not in dir file",
            )

    def combineDirInfoStatuses(
        self,
        dir_statuses: dict[str, Optional[tuple[int, Collection[str], str]]],
        status_key_list: list[str],
        best: bool = True,
        ignore_missing: bool = False,
    ) -> Optional[tuple[int, Collection[str], str]]:
        """Combine the directory statuses in dir_status, if their keys
        appear in status_key_list. Keys may be directory formats, or
        node nicks.

        If best is True, choose the best status, otherwise, choose the
        worst status.

        If ignore_missing is True, ignore missing statuses, if there is any
        other status available.

        If statuses are equal, combine their format sets.

        Returns None if the status list is empty.
        """
        dir_status_list = [
            dir_statuses[status_key]
            for status_key in dir_statuses
            if status_key in status_key_list
        ]

        if len(dir_status_list) == 0:
            return None

        dir_status = None
        for new_status in dir_status_list:
            if dir_status is None:
                dir_status = new_status
                continue

            (old_status_code, old_flav, old_msg) = dir_status
            (new_status_code, new_flav, new_msg) = new_status
            if new_status_code == old_status_code:
                # We want to know all the flavours that have an
                # equal status, not just the latest one
                combined_flav = old_flav.union(new_flav)
                dir_status = (old_status_code, combined_flav, old_msg)
            elif old_status_code == TorNet.MISSING_FILE_CODE and ignore_missing:
                # use the new status, which can't be MISSING_FILE_CODE,
                # because they're not equal
                dir_status = new_status
            elif new_status_code == TorNet.MISSING_FILE_CODE and ignore_missing:
                # ignore the new status
                pass
            elif old_status_code == TorNet.NOT_YET_IMPLEMENTED_CODE:
                # always ignore not yet implemented
                dir_status = new_status
            elif new_status_code == TorNet.NOT_YET_IMPLEMENTED_CODE:
                pass
            elif best and new_status_code > old_status_code:
                dir_status = new_status
            elif not best and new_status_code < old_status_code:
                dir_status = new_status
        return dir_status

    def summariseCacheDirInfoStatus(
        self,
        dir_status: dict[str, Optional[tuple[int, Collection[str], str]]],
        to_dir_server: int,
        to_bridge_client: int,
    ) -> Optional[tuple[int, Collection[str], str]]:
        """Summarise the statuses for this node, among all the files used by
        the other node.

        to_dir_server is True if the other node is a directory server.
        to_bridge_client is True if the other node is a bridge client.

        Combine these alternate files by choosing the best status:
          * desc_alts: "desc" and "desc_new"
          * md_alts: "md" and "md_new"

        Handle these alternate formats by ignoring missing directory files,
        then choosing the worst status:
          * cons_all: "ns_cons" and "md_cons"
          * desc_all: "desc"/"desc_new" and
                       "md"/"md_new"

        Add an "node_dir" status that describes the overall status, which
        is the worst status among descriptors, consensuses, and the bridge
        networkstatus (if relevant). Return this status.

        Returns None if no status is expected.
        """
        from_bridge = self.getBridge()
        # Is this node a bridge, publishing to a bridge client?
        bridge_to_bridge_client = self.getBridge() and to_bridge_client
        # Is this node a consensus relay, publishing to a bridge client?
        relay_to_bridge_client = self.getConsensusRelay() and to_bridge_client

        # We only need to be in one of these files to be successful
        desc_alts = self.combineDirInfoStatuses(
            dir_status, ["desc", "desc_new"], best=True, ignore_missing=True
        )
        if desc_alts:
            dir_status["desc_alts"] = desc_alts

        md_alts = self.combineDirInfoStatuses(
            dir_status, ["md", "md_new"], best=True, ignore_missing=True
        )
        if md_alts:
            dir_status["md_alts"] = md_alts

        if from_bridge:
            # Bridge clients fetch bridge descriptors directly from bridges
            # Bridges are not in the consensus
            cons_all = None
        elif to_dir_server:
            # Directory servers cache all flavours, so we want the worst
            # combined flavour status, and we want to treat missing files as
            # errors
            cons_all = self.combineDirInfoStatuses(
                dir_status, ["ns_cons", "md_cons"], best=False, ignore_missing=False
            )
        else:
            # Clients usually only fetch one flavour, so we want the best
            # combined flavour status, and we want to ignore missing files
            cons_all = self.combineDirInfoStatuses(
                dir_status, ["ns_cons", "md_cons"], best=True, ignore_missing=True
            )
        if cons_all:
            dir_status["cons_all"] = cons_all

        if bridge_to_bridge_client:
            # Bridge clients fetch bridge descriptors directly from bridges
            # Bridge clients fetch relay descriptors after fetching the consensus
            desc_all: Optional[tuple[int, Collection[str], str]] = dir_status[
                "desc_alts"
            ]
        elif relay_to_bridge_client:
            # Bridge clients usually fetch microdesc consensuses and
            # microdescs, but some fetch ns consensuses and full descriptors
            s = dir_status["md_alts"]
            if s is None:
                raise TorNet.ChutneyInternalError("Unexpectedly missing md_alts")
            md_status_code = s[0]
            if md_status_code == TorNet.MISSING_FILE_CODE:
                # If there are no md files, we're using descs for relays and
                # bridges
                desc_all = dir_status["desc_alts"]
            else:
                # If there are md files, we're using mds for relays, and descs
                # for bridges, but we're looking for a relay right now
                desc_all = dir_status["md_alts"]
        elif to_dir_server:
            desc_all = self.combineDirInfoStatuses(
                dir_status, ["desc_alts", "md_alts"], best=False, ignore_missing=False
            )
        else:
            desc_all = self.combineDirInfoStatuses(
                dir_status, ["desc_alts", "md_alts"], best=True, ignore_missing=True
            )
        if desc_all:
            dir_status["desc_all"] = desc_all

        # Finally, get the worst status from all the combined statuses,
        # and the bridge status (if applicable)
        node_dir = self.combineDirInfoStatuses(
            dir_status,
            ["cons_all", "br_status", "desc_all"],
            best=False,
            ignore_missing=True,
        )
        if node_dir:
            dir_status["node_dir"] = node_dir

        return node_dir

    def getNodeCacheDirInfoStatus(
        self,
        other_node_files: Optional[dict[str, Path]],
        to_dir_server: int,
        to_bridge_client: int,
    ) -> Optional[tuple[int, Collection[str], str]]:
        """Check all the directory paths used by another node, to see if this
        node is present.

        to_dir_server is True if the other node is a directory server.
        to_bridge_client is True if the other node is a bridge client.

        Returns a dict containing a status 3-tuple for every relevant
        directory format. See getFileDirInfoStatus() for more details.

        Returns None if the node doesn't have any directory files
        containing published information from this node.
        """
        dir_status: dict[str, Optional[tuple[int, Collection[str], str]]] = dict()
        # we don't expect the other node to have us in its files
        if other_node_files:
            for dir_format in other_node_files:
                dir_path = other_node_files[dir_format]
                new_status = self.getFileDirInfoStatus(dir_format, dir_path)
                if new_status is None:
                    continue
                dir_status[dir_format] = new_status

        if len(dir_status):
            return self.summariseCacheDirInfoStatus(
                dir_status, to_dir_server, to_bridge_client
            )
        else:
            # this node must be a client, or a bridge
            # (and the other node is not a bridge authority or bridge client)
            consensus_member = self.getConsensusMember()
            assert not consensus_member
            return None

    def getNodeDirInfoStatusList(
        self,
    ) -> Optional[dict[str, Optional[tuple[int, Collection[str], str]]]]:
        """Look through the directories on each node, and work out if
        this node is in that directory.

        Returns a dict containing a status 3-tuple for each relevant node.
        The 3-tuple contains:
          * a status code,
          * a list of formats with that status, and
          * a status message string.
        See getNodeCacheDirInfoStatus() and getFileDirInfoStatus() for
        more details.

        If this node is a directory authority, bridge authority, or relay
        (including exits), checks v3 directory consensuses, descriptors,
        microdesc consensuses, and microdescriptors.

        If this node is a bridge, checks bridge networkstatuses, and
        descriptors on bridge authorities and bridge clients.

        If this node is a client (including onion services), returns None.
        """
        dir_files = self.getNodePublishedDirInfoPaths()

        if not dir_files:
            return None

        dir_statuses = dict()
        # For all the nodes we expect will have us in their directory
        for other_node_nick in dir_files:
            (to_dir_server, to_bridge_client, other_node_files) = dir_files[
                other_node_nick
            ]
            if not other_node_files or not len(other_node_files):
                # we don't expect this node to have us in its files
                pass
            status = self.getNodeCacheDirInfoStatus(
                other_node_files, to_dir_server, to_bridge_client
            )
            dir_statuses[other_node_nick] = status

        if len(dir_statuses):
            return dir_statuses
        else:
            # this node must be a client
            # (or a bridge in a network with no bridge authority,
            # and no bridge clients, but chutney doesn't have networks like
            # that)
            consensus_member = self.getConsensusMember()
            bridge_member = self.getBridge()
            assert not consensus_member
            assert not bridge_member
            return None

    def summariseNodeDirInfoStatus(
        self,
        dir_status: Optional[dict[str, Optional[tuple[int, Collection[str], str]]]],
    ) -> Optional[
        dict[Union[int, str], tuple[int, Collection[str], Collection[str], str]]
    ]:
        """Summarise the statuses for this node's descriptor, among all the
        directory files used by all other nodes.

        Returns a dict containing a status 4-tuple for each status code.
        The 4-tuple contains:
          * a status code,
          * a list of the other nodes which have directory files with that
            status,
          * a list of directory file formats which have that status, and
          * a status message string.
        See getNodeCacheDirInfoStatus() and getFileDirInfoStatus() for
        more details.

        Also add an "node_all" status that describes the overall status,
        which is the worst status among all the other nodes' directory
        files.

        Returns None if no status is expected.
        """
        node_status: dict[
            Union[int, str], tuple[int, Collection[str], Collection[str], str]
        ] = dict()

        # check if we expect this node to be published to other nodes
        if dir_status:
            status_code_set = {
                status[0]
                for (other_node_nick, status) in dir_status.items()
                if status is not None
            }

            for status_code in status_code_set:
                other_node_nick_list = [
                    other_node_nick
                    for (other_node_nick, status) in dir_status.items()
                    if status is not None and status[0] == status_code
                ]

                comb_status = self.combineDirInfoStatuses(
                    dir_status, other_node_nick_list, best=False
                )

                if comb_status is not None:
                    (comb_code, comb_format_set, comb_msg) = comb_status
                    assert comb_code == status_code

                    node_status[status_code] = (
                        status_code,
                        other_node_nick_list,
                        comb_format_set,
                        comb_msg,
                    )

        node_all: Optional[tuple[int, Collection[str], Collection[str], str]] = None
        if len(node_status):
            # Finally, get the worst status from all the other nodes
            worst_status_code = min(status_code_set)
            node_all = node_status[worst_status_code]
        else:
            # this node should be a client
            # (or a bridge in a network with no bridge authority,
            # and no bridge clients, but chutney doesn't have networks like
            # that)
            consensus_member = self.getConsensusMember()
            bridge_member = self.getBridge()
            if consensus_member or bridge_member:
                node_all = (
                    TorNet.INTERNAL_ERROR_CODE,
                    set(),
                    set(),
                    "Expected {}{}{} dir info, but status is empty.".format(
                        "consensus" if consensus_member else "",
                        " and " if consensus_member and bridge_member else "",
                        "bridge" if bridge_member else "",
                    ),
                )
            else:
                # clients don't publish dir info
                node_all = None

        if node_all:
            node_status["node_all"] = node_all
            return node_status
        else:
            # client
            return None

    @override
    def getNodeDirInfoStatus(
        self,
    ) -> Optional[tuple[int, Collection[str], Collection[str], str]]:
        dir_status = self.getNodeDirInfoStatusList()
        if dir_status:
            summary = self.summariseNodeDirInfoStatus(dir_status)
            if summary:
                return summary["node_all"]

        # this node must be a client
        # (or a bridge in a network with no bridge authority,
        # and no bridge clients, but chutney doesn't have networks like
        # that)
        consensus_member = self.getConsensusMember()
        bridge_member = self.getBridge()
        assert not consensus_member
        assert not bridge_member
        return None

    def isInExpectedDirInfoDocs(self) -> Optional[bool]:
        """Return True if the descriptors for this node are in all expected
        directory documents.

        Return None if this node does not publish descriptors.
        """
        node_status = self.getNodeDirInfoStatus()
        if node_status:
            status_code, _, _, _ = node_status
            return status_code == TorNet.SUCCESS_CODE
        else:
            # Clients don't publish descriptors, so they are always ok.
            # (But we shouldn't print a descriptor status for them.)
            return None
