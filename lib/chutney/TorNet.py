#!/usr/bin/env python
#
# Copyright 2011 Nick Mathewson, Michael Stone
# Copyright 2013 The Tor Project
#
#  You may do anything with this work that copyright law would normally
#  restrict, so long as you retain the above notice(s) and this license
#  in all redistributed copies and derived works.  There is no warranty.

# [pep 0536](https://peps.python.org/pep-0563/) - Lazy annotation eval via
# stringification.
from __future__ import annotations

# Future imports for Python 2.7, mandatory in 3.0
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, TypeVar, Any, Iterable, Union

import copy
import dataclasses
import errno
import importlib
import importlib.resources
import os
import platform
import re
import signal
import subprocess
import sys
import textwrap
import time
import json
import shutil

from chutney.Debug import debug
from chutney.Util import (
    getenv_int,
    getenv_bool,
    launch_process,
    Option,
    OptionalConversionDescriptor,
)
from chutney.network_tests import NetworkTestFailure
from chutney.tor.util import get_tor_version, run_tor
from collections.abc import Collection
from importlib.abc import Traversable
from typeguard import check_type
from typing_extensions import override

import chutney.tor.torrc
import chutney.Host
import chutney.Util

V3_AUTH_VOTING_INTERVAL = 20.0

_TOR_VERSIONS = None
_TORRC_OPTIONS = None

TORRC_OPTION_WARN_LIMIT = 10
torrc_option_warn_count = 0

# descriptor constants
INTERNAL_ERROR_CODE = -500
MISSING_FILE_CODE = -400
NO_RECORDS_CODE = -300
NOT_YET_IMPLEMENTED_CODE = -200
SHORT_FILE_CODE = -100
NO_PROGRESS_CODE = 0
SUCCESS_CODE = 100
ONIONDESC_PUBLISHED_CODE = 200
HSV2_KEYWORD = "hidden service v2"
HSV3_KEYWORD = "hidden service v3"


class ChutneyError(Exception):
    """Base class for "normal" errors originating from this module

    i.e. any public functions in this module raising an exception that *isn't*
    a subclass of this indicates a programming error in this module.
    """

    pass


class ChutneyMissingBinaryError(ChutneyError):
    def __init__(self, name: str, cmdline: List[str], help: str):
        self._name = name
        self._cmdline = cmdline
        self._help = help

    @staticmethod
    def for_missing_tor(tor_name: str, cmdline: List[str]) -> ChutneyMissingBinaryError:
        """Create an exception for a missing tor binary, with help for how to fix it."""
        help_msg_fmt = (
            "Set the '{0}' environment variable to the path of "
            + "'{1}'. If using test-network.sh, set the 'TOR_DIR' "
            + "environment variable to the directory containing '{1}'."
        )
        help_msg = ""
        if tor_name == "tor":
            help_msg = help_msg_fmt.format("CHUTNEY_TOR", tor_name)
        elif tor_name == "tor-gencert":
            help_msg = help_msg_fmt.format("CHUTNEY_TOR_GENCERT", tor_name)
        else:
            raise ValueError("Unknown tor_name: '{}'".format(tor_name))
        return ChutneyMissingBinaryError(tor_name, cmdline, help_msg)

    def __str__(self) -> str:
        return (
            f"Cannot find the {self._name} binary"
            + f" at '{self._cmdline[0]}'"
            + f" for the command line '{' '.join(self._cmdline)}'."
            + f" {self._help}"
        )


class ChutneyTimeoutError(ChutneyError):
    pass


class ChutneyInconsistentTemplateError(ChutneyError):
    def __init__(self, template_name: str, pattern: str, contents: str):
        self._template_name = template_name
        self._pattern = pattern
        self._contents = contents

    def __str__(self) -> str:
        return (
            f"Couldn't find expected pattern '{self._pattern}'."
            + " Check that other config options have been set consistently"
            + f" with specified template name '{self._template_name}'."
            + "\nFull generated torrc:\n"
            + textwrap.indent(self._contents, "  ")
        )


class ChutneyErrorGroup(ChutneyError):
    """A list of errors.

    For use in methods like `start` where we want to continue after the first error,
    but collect all of the errors.

    Analogous to python 3.11's `ExceptionGroup`
    """

    def __init__(self, description: str, errs: List[ChutneyError]):
        self._description = description
        self._errs = errs
        ChutneyError.__init__(self, description, errs)

    def __str__(self) -> str:
        return (
            self._description
            + " [\n  "
            + "\n  ".join([str(e) for e in self._errs])
            + "\n]\n"
        )


class ChutneyInternalError(ChutneyError):
    """Indicates a bug in Chutney"""

    pass


T = TypeVar("T")


def mkdir_p(*d: Union[str, Path], mode: int = 448) -> None:
    """Create directory 'd' and all of its parents as needed.  Unlike
    os.makedirs, does not give an error if d already exists.

    448 is the decimal representation of the octal number 0700. Since
    python2 only supports 0700 and python3 only supports 0o700, we can use
    neither.

    Note that python2 and python3 differ in how they create the
    permissions for the intermediate directories.  In python3, 'mode'
    only sets the mode for the last directory created.
    """
    Path(*d).mkdir(mode=mode, parents=True, exist_ok=True)


def make_datadir_subdirectory(
    datadir: Union[str, Path], subdir: Union[str, Path]
) -> None:
    """
    Create a datadirectory (if necessary) and a subdirectory of
    that datadirectory.  Ensure that both are mode 700.
    """
    mkdir_p(datadir)
    mkdir_p(datadir, subdir)


def get_absolute_chutney_path() -> Path:
    """
    Returns the absolute path of the directory containing the chutney
    executable script.
    """
    # use the current directory as the default
    # (./chutney already sets CHUTNEY_PATH using the path to the script)
    # use tools/test-network.sh if you want chutney to try really hard to find
    # itself
    relative_chutney_path = Path(os.environ.get("CHUTNEY_PATH", os.getcwd()))
    return relative_chutney_path.resolve()


def get_absolute_net_path() -> Path:
    """
    Returns the absolute path of the "net" directory that chutney should
    use to store "node*" directories containing torrcs and tor runtime data.

    If the CHUTNEY_DATA_DIR environmental variable is an absolute path, it
    is returned unmodified, regardless of whether the path actually exists.
    (Chutney creates any directories that do not exist.)

    Otherwise, if it is a relative path, and there is an existing directory
    with that name in the directory containing the chutney executable
    script, return that path (this check exists for legacy reasons).

    Finally, return the path relative to the current working directory,
    regardless of whether the path actually exists.
    """
    data_dir = Path(os.environ.get("CHUTNEY_DATA_DIR", "net"))
    if data_dir.is_absolute():
        # if we are given an absolute path, we should use it
        # regardless of whether the directory exists
        return data_dir
    # use the chutney path as the default
    absolute_chutney_path = get_absolute_chutney_path()
    relative_net_path = Path(data_dir)
    # but what is it relative to?
    # let's check if there's an existing directory with this name in
    # CHUTNEY_PATH first, to preserve backwards-compatible behaviour
    chutney_net_path = Path(absolute_chutney_path, relative_net_path)
    if chutney_net_path.is_dir():
        return chutney_net_path
    # ok, it's relative to the current directory, whatever that is, and whether
    # or not the path actually exists
    return relative_net_path.resolve()


def get_absolute_nodes_path() -> Path:
    """
    Returns the absolute path of the "nodes" symlink that points to the
    "nodes*" directory that chutney should use to store the current
    network's torrcs and tor runtime data.

    This path is also used as a prefix for the unique nodes directory
    names.

    See get_new_absolute_nodes_path() for more details.
    """
    return Path(get_absolute_net_path(), "nodes")


def get_new_absolute_nodes_path(now: float = time.time()) -> Path:
    """
    Returns the absolute path of a unique "nodes*" directory that chutney
    should use to store the current network's torrcs and tor runtime data.

    The nodes directory suffix is based on the current timestamp,
    incremented if necessary to avoid collisions with existing directories.

    (The existing directory check contains known race conditions: running
    multiple simultaneous chutney instances on the same "net" directory is
    not supported. The uniqueness check is only designed to avoid
    collisions if the clock is set backwards.)
    """
    # automatically chosen to prevent path collisions, and result in an ordered
    # series of directory path names
    # should only be called by 'chutney configure', all other chutney commands
    # should use get_absolute_nodes_path()
    nodesdir = get_absolute_nodes_path()
    newdir = newdirbase = Path("%s.%d" % (nodesdir, now))
    # if the time is the same, fall back to a simple integer count
    # (this is very unlikely to happen unless the clock changes: it's not
    # possible to run multiple chutney networks at the same time)
    i = 0
    while newdir.exists():
        i += 1
        newdir = Path("%s.%d" % (newdirbase, i))
    return newdir


def get_familykey_path(ident: Optional[str], ext: bool = True) -> Path:
    """
    Return the absolute path for the secret family key identified with `ident`.

    If no ident is given, return the directory in which we store family keys.

    If `ext` is false, omit the "secret_family_key" exension.
    """
    family_key_dir = get_absolute_nodes_path().joinpath("family_keys")
    if ident is None:
        return family_key_dir
    if ext:
        fn = f"{ident}.secret_family_key"
    else:
        fn = ident
    return family_key_dir.joinpath(fn)


def run_tor_gencert(cmdline: List[str], passphrase: str) -> str:
    """Run the tor-gencert command line cmdline, which must start with the
    path or name of a tor-gencert binary.
    Then send passphrase to the stdin of the process.

    Returns the combined stdout and stderr of the process.
    """
    p = launch_process(cmdline, tor_name="tor-gencert", stdin=subprocess.PIPE)
    (stdouterr, empty_stderr) = p.communicate(passphrase + "\n")
    debug(stdouterr)
    assert p.returncode == 0  # XXXX BAD!
    assert empty_stderr is None
    return stdouterr


@chutney.Util.memoized
def tor_exists(tor: str) -> bool:
    """Return true iff this tor binary exists."""
    try:
        run_tor([tor, "--hush", "--version"])
        return True
    except ChutneyMissingBinaryError:
        return False


@chutney.Util.memoized
def tor_gencert_exists(gencert: str) -> bool:
    """Return true iff this tor-gencert binary exists."""
    try:
        p = launch_process([gencert, "--help"])
        p.wait()
        return True
    except ChutneyMissingBinaryError:
        return False


@chutney.Util.memoized
def get_torrc_options(tor: str) -> list[str]:
    """Return the torrc options supported by the tor binary.
    Options are cached for each unique tor path.
    """
    cmdline = [
        tor,
        "--list-torrc-options",
    ]
    opts = run_tor(cmdline)
    # check we received a list of options, and nothing else
    assert re.match(r"(^\w+$)+", opts, flags=re.MULTILINE)
    torrc_opts = opts.split()

    return torrc_opts


@chutney.Util.memoized
def get_tor_modules(tor: str) -> dict[str, bool]:
    """Check the list of compile-time modules advertised by the given
    'tor' binary, and return a map from module name to a boolean
    describing whether it is supported.

    Unlisted modules are ones that Tor did not treat as compile-time
    optional modules.
    """
    cmdline = [tor, "--list-modules", "--hush"]
    try:
        mods = run_tor(cmdline)
    except subprocess.CalledProcessError:
        # Tor doesn't support --list-modules; act as if it said nothing.
        mods = ""

    supported = {}
    for line in mods.split("\n"):
        m = re.match(r"^(\S+): (yes|no)", line)
        if not m:
            continue
        supported[m.group(1)] = m.group(2) == "yes"

    return supported


@chutney.Util.memoized
def _hs_hostname(hs_directory: Path) -> str:
    """Generated hostname for a hidden service"""
    # a file containing a single line with the hs' .onion address
    hs_hostname_file = Path(hs_directory, "hostname")
    try:
        with open(hs_hostname_file, "r") as hostnamefp:
            hostname = hostnamefp.read()
        # the hostname file ends with a newline
        hostname = hostname.strip()
        return hostname
    except IOError as e:
        raise ChutneyError("Error opening hostname file") from e


def tor_has_module(tor: str, modname: str, default: bool = True) -> bool:
    """Return true iff the given tor binary supports a given compile-time
    module.  If the module is not listed, return 'default'.
    """
    return get_tor_modules(tor).get(modname, default)


class Node(object):
    """A Node represents a Tor node or a set of Tor nodes.  It's created
    in a network configuration file.

    This class is responsible for holding the user's selected node
    configuration, and figuring out how the node needs to be
    configured and launched.
    """

    def __init__(self, network: Network, config: NodeConfig, nodenum: int):
        """Create a new Node.

        This should generally only be called by Network, to create a node as
        it's being added.
        """
        # chutney's internal node number for the node
        self.nodenum: int = nodenum

        # Validate some fields. NodeConfig permits these to be None
        # for use with templating; e.g. NodeConfig.specialize.
        self.tag: str = Option(config.tag).unwrap(
            lambda: f"Config is missing 'tag': {config}"
        )

        # These gets set by Builder.preConfigBuild.
        # TODO: make `Optional` and init to `None`?
        # TODO: move onto the builder? Or a "builder output" field?
        self.fingerprint: Option[str] = Option(None)
        self.fingerprint_ed25519: Option[str] = Option(None)
        self.ed25519_id: Option[str] = Option(None)
        self.family_id_lines: Option[list[str]] = Option(None)
        self.myfamily_members: Option[list[str]] = Option(None)

        self._network = network
        self._config = config
        self._builder: Optional[NodeBuilder] = None
        self._controller: Optional[NodeController] = None

    @property
    def orport(self) -> int:
        """OrPort that this node exposes"""
        return self._network.orport_base + self.nodenum

    @property
    def controlport(self) -> int:
        """ControlPort that this node exposes"""
        return self._network.controlport_base + self.nodenum

    @property
    def socksport(self) -> Option[int]:
        """SocksPort that this node exposes, if any."""
        if self._config.client:
            return Option(self._network.socksport_base + self.nodenum)
        else:
            return Option(None)

    @property
    def dirport(self) -> Option[int]:
        """DirPort that this node exposes"""
        if self._config.relay and not self._config.bridge:
            return Option(self._network.dirport_base + self.nodenum)
        else:
            return Option(None)

    @property
    def extorport(self) -> int:
        """Extended ORPort that this node exposes"""
        return self._network.extorport_base + self.nodenum

    @property
    def ptport(self) -> int:
        """Port to listen on as a pluggble transport bridge (ServerTransportListenAddr)"""
        return self._network.ptport_base + self.nodenum

    @property
    def dir(self) -> Path:
        """Directory where this node stores its configuration and data (DataDirectory)"""
        return Path(
            self._network.dir,
            "%03d%s" % (self.nodenum, self._config.tag),
        ).resolve()

    @property
    def torrc_fname(self) -> str:
        return f"{self.dir}/torrc"

    @property
    def controlsocket(self) -> Optional[Path]:
        """ControlSocket that this node exposes"""
        if self._config.enable_controlsocket:
            return self.dir.joinpath("control")
        else:
            return None

    @property
    def nick(self) -> str:
        """Nickname for this node on the network (debugging only)"""
        return "test%03d%s" % (self.nodenum, self._config.tag)

    @property
    def auth_passphrase(self) -> str:
        """Obsoleted by CookieAuthentication"""
        # TODO: remove?
        return self.nick  # OMG TEH SECURE!

    @property
    def lockfile(self) -> Path:
        """Path to this node's lockfile"""
        return Path(self.dir, "lock")

    @property
    def pidfile(self) -> Path:
        """Path to this node's PidFile"""
        return Path(self.dir, "pid")

    # A hs generates its key on first run,
    # so check for it at the last possible moment,
    # but cache it in memory to avoid repeatedly reading the file
    # XXXX - this is not like the other functions in this class,
    # as it reads from a file created by the hidden service
    @property
    def hs_hostname(self) -> str:
        """Generated hostname for this hidden service"""
        # Call memoized helper function.
        return _hs_hostname(Path(self.dir, self._config.hs_directory))

    ######
    # Chutney uses these:

    def getBuilder(self) -> NodeBuilder:
        """Return a NodeBuilder instance to set up this node (that is, to
        write all the files that need to be in place so that this
        node can be run by a NodeController).
        """
        if self._builder is None:
            self._builder = LocalNodeBuilder(self)
        return self._builder

    def getController(self) -> NodeController:
        """Return a NodeController instance to control this node (that is,
        to start it, stop it, see if it's running, etc.)
        """
        from chutney.tor.controller import LocalNodeController

        if self._controller is None:
            self._controller = LocalNodeController(self._network, self)
        return self._controller

    def isOnionService(self) -> bool:
        """Is this node an onion service?"""
        return self.tag.startswith("h") or self._config.hs


class NodeBuilder(ABC):
    """Abstract base class.  A NodeBuilder is responsible for doing all the
    one-time prep needed to set up a node in a network.
    """

    @abstractmethod
    def checkConfig(self, net: Network) -> None:
        """Try to format our torrc; raise an exception if we can't."""
        ...

    @abstractmethod
    def preConfig(self, net: Network) -> None:
        """Called on all nodes before any nodes configure: generates keys and
        hidden service directories as needed.
        """
        ...

    @abstractmethod
    def config(self, net: Network) -> None:
        """Called to configure a node: creates a torrc file for it."""
        ...

    @abstractmethod
    def postConfig(self, net: Network) -> None:
        """Called on each nodes after all nodes configure."""
        ...

    @abstractmethod
    def isSupported(self, net: Network) -> bool:
        """Return true if this node appears to have everything it needs;
        false otherwise."""
        ...

    @abstractmethod
    def getAltAuthLines(self, hasbridgeauth: bool = False) -> Optional[AuthorityLine]:
        """Return the information needed to use this node as an authority,
        if it is configured as one.
        """
        ...

    @abstractmethod
    def getBridgeLines(self) -> list[BridgeLine]:
        """Return descriptors that a client can use to connect to this bridge.
        Non-bridge relays return [].
        """
        ...


class NodeController(ABC):
    """Abstract base class.  A NodeController is responsible for running a
    node on the network.
    """

    @abstractmethod
    def check(self, listRunning: bool = True, listNonRunning: bool = False) -> bool:
        """See if this node is running, stopped, or crashed.  If it's running
        and listRunning is set, print a short statement.  If it's
        stopped and listNonRunning is set, then print a short statement.
        If it's crashed, print a statement.  Return True if the
        node is running, false otherwise.
        """
        ...

    @abstractmethod
    def isRunning(self) -> bool:
        """Return true iff this node is running."""
        ...

    @abstractmethod
    def start(self) -> None:
        """Try to start this node, if not already running. Raises `ChutneyError` on failure."""
        ...

    @abstractmethod
    def stop(self, sig: int = signal.SIGINT) -> None:
        """Try to stop this node by sending it the signal 'sig'."""
        ...

    @abstractmethod
    def getPtExtra(self) -> Option[str]:
        """Get extra bridge info to use this node as a PT bridge.

        Returns an empty string if there is no such info (e.g. this isn't a PT bridge).
        Returns None if we *expect* there to be such info but couldn't locate it (yet).
        """
        ...

    @abstractmethod
    def hup(self) -> bool:
        """Send a SIGHUP to this node, if it's running."""
        ...

    @abstractmethod
    def cleanupRunFiles(self) -> None:
        """Clean up any left-over run state, assuming the node has exited."""
        ...

    @abstractmethod
    def getNodeCacheDirInfoPaths(
        self, v2_dir_paths: bool
    ) -> tuple[int, int, Optional[dict[str, Path]]]:
        """Return a 3-tuple containing:
          * a boolean indicating whether this node is a directory server,
            (that is, an authority, relay, or bridge),
          * a boolean indicating whether this node is a bridge client, and
          * a dict with the expected paths to the consensus files for this
            node.

        If v2_dir_paths is True, returns the v3 directory paths.
        Otherwise, returns the bridge status path.
        If v2_dir_paths is True, but this node is not a bridge client or
        bridge authority, returns None. (There are no paths.)

        Directory servers usually have both consensus flavours.
        Clients usually have the microdesc consensus, but they may have
        either flavour. (Or both flavours.)
        Only the bridge authority has the bridge networkstatus.

        The dict keys are:
          * "ns_cons", "desc", and "desc_new";
          * "md_cons", "md", and "md_new"; and
          * "br_status".
        """
        ...

    @abstractmethod
    def getUncheckedDirInfoWaitTime(self) -> float:
        """Returns the amount of time to wait before verifying, after the
        network has bootstrapped, and the dir info has been distributed.

        Based on whether this node has unchecked directory info, or other
        known timing issues.
        """
        ...

    @abstractmethod
    def getNick(self) -> str:
        """Return the nickname for this node."""
        ...

    @abstractmethod
    def updateLastStatus(self) -> None:
        """Update last messages this node has received, for use with
        isBootstrapped and the getLast* functions.
        """
        ...

    @abstractmethod
    def updateLastBootstrapStatus(self) -> None:
        """Look through the logs and cache the last bootstrap message
        received.
        """
        ...

    @abstractmethod
    def getLastBootstrapStatus(self) -> tuple[int, str, str]:
        """Return the last bootstrap message fetched by
        updateLastBootstrapStatus as a 3-tuple of percentage
        complete, keyword (optional), and message.

        The return status depends on the last time updateLastStatus()
        was called; that function must be called before this one.
        """
        ...

    @abstractmethod
    def isBootstrapped(self) -> bool:
        """Return true iff the logfile says that this instance is
        bootstrapped.

        The return status depends on the last time updateLastStatus()
        was called; that function must be called before this one.
        """
        ...

    @abstractmethod
    def getNodeDirInfoStatus(
        self,
    ) -> Optional[tuple[int, Collection[str], Collection[str], str]]:
        """Return a 4-tuple describing the status of this node's descriptor,
        in all the directory documents across the network.

        If this node does not have a descriptor, returns None.
        """
        ...

    @abstractmethod
    def getConsensusAuthority(self) -> bool:
        """Is this node a consensus (V2 directory) authority?"""
        ...


class LocalNodeBuilder(NodeBuilder):

    # Environment members used:
    # torrc -- which torrc file to use
    # authority -- bool -- are we an authority? (includes bridge authorities)
    # bridgeauthority -- bool -- are we a bridge authority?
    # relay -- bool -- are we a relay? (includes exits and bridges)
    # bridge -- bool -- are we a bridge?
    # hs -- bool -- are we a hidden service?
    # nodenum -- int -- set by chutney -- which unique node index is this?
    # dir -- path -- set by chutney -- data directory for this tor
    # tor_gencert -- path to tor_gencert binary
    # tor -- path to tor binary
    # auth_cert_lifetime -- lifetime of authority certs, in months.
    # ip -- primary IP address (usually IPv4) to listen on
    # ipv6_addr -- secondary IP address (usually IPv6) to listen on
    # orport, dirport -- used on authorities, relays, and bridges. The orport
    #                    is used for both IPv4 and IPv6, if present
    # fingerprint, fingerprint_ed -- used only if authority
    # dirserver_flags -- used only if authority
    # nick -- nickname of this router

    # Environment members set
    # fingerprint -- hex router key fingerprint
    # fingerprint_ed -- base64 router key ed25519 fingerprint
    # nodenum -- int -- set by chutney -- which unique node index is this?

    def __init__(self, node: Node):
        NodeBuilder.__init__(self)
        self._node = node

    def _createTorrcFile(self, checkOnly: bool = False) -> None:
        """Write the torrc file for this node, disabling any options
        that are not supported by config's tor binary using comments.
        If checkOnly, just make sure that the formatting is indeed
        possible.
        """
        global torrc_option_warn_count

        fn_out = self._node.torrc_fname
        output = self._getTorrcContents()
        if checkOnly:
            # XXXX Is it time-consuming to format? If so, cache here.
            return
        # now filter the options we're about to write, commenting out
        # the options that the current tor binary doesn't support
        tor = self._node._config.tor
        tor_version = get_tor_version(tor)
        torrc_opts = get_torrc_options(tor)
        # check if each option is supported before writing it
        # Unsupported option values may need special handling.
        with open(fn_out, "w") as f:
            # we need to do case-insensitive option comparison
            lower_opts = [opt.lower() for opt in torrc_opts]
            # keep ends when splitting lines, so we can write them out
            # using writelines() without messing around with "\n"s
            for line in output.splitlines(True):
                # check if the first word on the line is a supported option,
                # preserving empty lines and comment lines
                sline = line.strip()
                if (
                    len(sline) == 0
                    or sline[0] == "#"
                    or sline.split()[0].lower() in lower_opts
                ):
                    pass
                else:
                    warn_msg = (
                        "The tor binary at {} does not support "
                        + "the option in the torrc line:\n{}"
                    ).format(tor, line.strip())
                    if torrc_option_warn_count < TORRC_OPTION_WARN_LIMIT:
                        print(warn_msg)
                        torrc_option_warn_count += 1
                    else:
                        debug(warn_msg)
                    # always dump the full output to the torrc file
                    line = "# {} version {} does not support: {}".format(
                        tor, tor_version, line
                    )
                f.writelines([line])
        # Verify that the resulting config parses.  If we move or remove this
        # check, ensure that `tests/torrc-template-tests` and `tests/network-config-tests`
        # still actually validate the generated config files.
        run_tor(
            [
                str(self._node._config.tor),
                "-f",
                self._node.torrc_fname,
                "--verify-config",
            ]
        )

    def _getTorrcContents(self) -> str:
        """Return the filled template used to write the torrc for this node."""
        return chutney.tor.torrc.format(self._node)

    @override
    def checkConfig(self, net: Network) -> None:
        self._createTorrcFile(checkOnly=True)

    @override
    def preConfig(self, net: Network) -> None:
        self._makeDataDir()
        if self._node._config.authority:
            self._genAuthorityKey()
        if self._node._config.relay:
            self._genRouterKey()
        if self._node._config.hs:
            self._makeHiddenServiceDir()
        if self._node._config.families:
            lines: list[str] = []
            for fid in self._node._config.families:
                if net.family_id_lines:
                    shutil.copy(get_familykey_path(fid), Path(self._node.dir, "keys"))
                    lines.append(net.family_id_lines[fid])
            self._node.family_id_lines = Option(lines)
        else:
            self._node.family_id_lines = Option([])

    @override
    def config(self, net: Network) -> None:
        if self._node._config.families:
            # We have to do this now that the keys are loaded.
            myfamily = []
            for other in net._nodes:
                if not other._config.families:
                    continue
                if any(
                    fid in other._config.families for fid in self._node._config.families
                ):
                    # "Other" is in this node's family.
                    myfamily.append(other.fingerprint.unwrap())
            self._node.myfamily_members = Option(myfamily)
        else:
            self._node.myfamily_members = Option([])

        self._createTorrcFile()
        # self._createScripts()

    @override
    def postConfig(self, net: Network) -> None:
        # self.net.addNode(self)
        pass

    @override
    def isSupported(self, net: Network) -> bool:
        if not tor_exists(self._node._config.tor):
            print("No binary found for %r" % self._node._config.tor)
            return False

        if self._node._config.authority:
            if not tor_has_module(self._node._config.tor, "dirauth"):
                print("No dirauth support in %r" % self._node._config.tor)
                return False
            if not tor_gencert_exists(self._node._config.tor_gencert):
                print(
                    "No binary found for tor-gencert %r"
                    % self._node._config.tor_gencert
                )
                return False

        return True

    def _makeDataDir(self) -> None:
        """Create the data directory (with keys subdirectory) for this node."""
        datadir = check_type(self._node.dir, Path)
        make_datadir_subdirectory(datadir, "keys")

    def _makeHiddenServiceDir(self) -> None:
        """Create the hidden service subdirectory for this node.

        The directory name is stored under the 'hs_directory' environment
        key. It is combined with the 'dir' data directory key to yield the
        path to the hidden service directory.
        """
        datadir = self._node.dir
        make_datadir_subdirectory(datadir, self._node._config.hs_directory)

    def _genAuthorityKey(self) -> None:
        """Generate an authority identity and signing key for this authority,
        if they do not already exist."""
        datadir = self._node.dir
        tor_gencert = self._node._config.tor_gencert
        lifetime = self._node._config.auth_cert_lifetime
        idfile = Path(datadir, "keys", "authority_identity_key")
        skfile = Path(datadir, "keys", "authority_signing_key")
        certfile = Path(datadir, "keys", "authority_certificate")
        addr = f"{self._node._config.ip.unwrap()}:{self._node.dirport.unwrap()}"
        passphrase = self._node.auth_passphrase
        if all(f.exists() for f in [idfile, skfile, certfile]):
            return
        cmdline = [
            tor_gencert,
            "--create-identity-key",
            "--passphrase-fd",
            "0",
            "-i",
            str(idfile),
            "-s",
            str(skfile),
            "-c",
            str(certfile),
            "-m",
            str(lifetime),
            "-a",
            addr,
        ]
        # nicknames are testNNNaa[OLD], but we want them to look tidy
        print(
            "Creating identity key for {:12} with {}".format(
                self._node.nick, cmdline[0]
            )
        )
        debug("Identity key path '{}', command '{}'".format(idfile, " ".join(cmdline)))
        run_tor_gencert(cmdline, passphrase)

    def _genRouterKey(self) -> None:
        """Generate an identity key for this router, unless we already have,
        and set up the 'fingerprint' entry in the Environ.
        """
        datadir = self._node.dir
        tor = self._node._config.tor
        torrc = self._node.torrc_fname
        cmdline: list[str] = [
            tor,
            "--ignore-missing-torrc",
            "-f",
            torrc,
            "--orport",
            "1",
            "--datadirectory",
            str(datadir),
            "--list-fingerprint",
        ]
        stdouterr = run_tor(cmdline)
        fingerprint = "".join((stdouterr.rstrip().split("\n")[-1]).split()[1:])
        if not re.match(r"^[A-F0-9]{40}$", fingerprint):
            raise ChutneyError(
                "Error when getting fingerprint using '{0}'. It output '{1}'.".format(
                    repr(" ".join(cmdline)), repr(stdouterr)
                )
            )
        self._node.fingerprint.replace(fingerprint)

        ed_fn = os.path.join(datadir, "fingerprint-ed25519")
        if os.path.exists(ed_fn):
            s = open(ed_fn).read().strip().split()[1]
            self._node.fingerprint_ed25519.replace(s)

    @override
    def getAltAuthLines(self, hasbridgeauth: bool = False) -> Optional[AuthorityLine]:
        if not self._node._config.authority:
            return None

        datadir = self._node.dir
        certfile = Path(datadir, "keys", "authority_certificate")
        v3id = None
        with certfile.open(mode="r") as f:
            for line in f:
                if line.startswith("fingerprint"):
                    v3id = line.split()[1].strip()
                    break

        assert v3id is not None

        return AuthorityLine(
            nick=self._node.nick,
            ipv4=self._node._config.ip.unwrap(),
            ipv6=self._node._config.ipv6_addr,
            orport=self._node.orport,
            dirport=self._node.dirport.unwrap(),
            v3id=v3id,
            fingerprint=self._node.fingerprint.unwrap(),
            fingerprint_ed25519=self._node.fingerprint_ed25519.unwrap(),
            alt_bridge_auth=self._node._config.bridgeauthority,
            alt_dir_auth=not self._node._config.bridgeauthority,
            extra_flags=self._node._config.dirserver_flags.split(),
        )

    @override
    def getBridgeLines(self) -> list[BridgeLine]:
        if not self._node._config.bridge:
            return []

        if self._node._config.pt_bridge:
            port = self._node.ptport
            pt_transport = Option(self._node._config.pt_transport)
            pt_extra = self._node.getController().getPtExtra()
            if pt_extra.is_none():
                # obfs4 pt bridges (and possibly others) don't generate their
                # `pt_extra` until after they've *started*.  We should probably
                # return `[]` here, or avoid calling this function at all for a
                # pt bridge that hasn't started yet.  For now we preserve legacy
                # behavior of just setting pt_extra to an empty string, which
                # causes validation to pass, but a pt bridge client won't
                # actually be able to connect.
                # TODO(#40023): Once #40023 is fixed, revisit doing something else here.
                debug(f"Couldn't load pt_extra from {self._node.dir}")
                pt_extra = Option("")
        else:
            # the orport is the same on IPv4 and IPv6
            port = self._node.orport
            pt_transport = Option(None)
            pt_extra = Option(None)

        res = [
            BridgeLine(
                ipaddr=self._node._config.ip.unwrap(),
                port=port,
                fingerprint=self._node.fingerprint.unwrap(),
                pt_transport=pt_transport,
                pt_extra=pt_extra,
            ),
        ]
        if self._node._config.ipv6_addr.is_some():
            res.append(
                BridgeLine(
                    ipaddr=self._node._config.ipv6_addr.unwrap(),
                    port=port,
                    fingerprint=self._node.fingerprint.unwrap(),
                    pt_transport=pt_transport,
                    pt_extra=pt_extra,
                )
            )
        return res


CUR_CONFIG_PHASE: int = getenv_int("CHUTNEY_CONFIG_PHASE", 1)
CUR_LAUNCH_PHASE: int = getenv_int("CHUTNEY_LAUNCH_PHASE", 1)
CUR_BOOTSTRAP_PHASE: int = getenv_int("CHUTNEY_BOOTSTRAP_PHASE", 1)


@dataclasses.dataclass
class NodeConfig:
    """Properties of a Tor Node"""

    # a short text string that represents the type of node.
    # Some special tag prefixes:
    # * 'h' configures it to run an onion service.
    # * 'c' and 'bc' cause the `verify` test to recognize it as a client.
    #   (as does setting the `client` attribute).
    # TODO: Get rid of these special tag meanings in favor of explicit attributes.
    tag: Optional[str] = None
    # Whether to configure this node to use a bridge.
    bridgeclient: bool = False
    # Whether to configure this node to act as a client.
    client: bool = False
    # Whether to configure this node to act as an exit.
    exit: bool = False

    # Whether to configure this node to act as an authority (or bridge authority).
    authority: bool = False
    # Whether to configure this node as a bridge authority
    bridgeauthority: bool = False
    # Whether to configure this node as a relay; including as an exit, or bridge
    relay: bool = False
    # Whether to configure this node as a bridge.
    bridge: bool = False
    # Whether to configure this node as a pluggable transport bridge.
    pt_bridge: bool = False
    # Name of pluggable transport to use for a bridge or bridge client.
    pt_transport: str = ""
    # Executable that implements the pluggable transport.
    pt_executable: Path = Path("obfs4proxy")
    # Whether to configure this node as a hidden service
    hs: bool = False
    # directory (relative to datadir) to store hidden service info
    hs_directory: str = "hidden_service"
    # if creating a hidden service, whether to configure it as single-hop.
    hs_singlehop: bool = False
    # value of ConnLimit torrc option
    connlimit: int = 60
    # path of the tor binary
    tor: str = os.environ.get("CHUTNEY_TOR", "tor")
    # lifetime of authority certs, in months
    auth_cert_lifetime: int = 12
    # primary IP address (usually IPv4) to listen on.
    # Setting to None disables ipv4.
    ip: OptionalConversionDescriptor[str] = OptionalConversionDescriptor(
        default=Option(os.environ.get("CHUTNEY_LISTEN_ADDRESS", "127.0.0.1"))
    )
    # secondary IP address (usually IPv6) to listen on. we default to
    # ipv6_addr=None to support IPv4-only systems.
    # We use OptionalConversionDescriptor here to get `Option[str]`'s
    # enforcement for our internal usage, but allow callers to initialize and
    # assign as if it were `Optional[str]`.
    ipv6_addr: OptionalConversionDescriptor[str] = OptionalConversionDescriptor(
        default=Option(os.environ.get("CHUTNEY_LISTEN_ADDRESS_V6", None))
    )
    # Whether to disable all ipv6 functionality
    disableipv6: bool = getenv_bool("CHUTNEY_DISABLE_IPV6", False)
    # Directory server flags. Used only if authority=True
    dirserver_flags: str = "no-v2"
    # None means wait on launch (requires RunAsDaemon),
    # otherwise, poll after that many seconds (can be fractional/decimal)
    poll_launch_time: Optional[float] = None
    # Used when poll_launch_time is None, but
    # RunAsDaemon is not set Set low so that we don't interfere with the
    # voting interval
    poll_launch_time_default: float = 0.1
    # The PID of the controlling script
    # (for __OwningControllerProcess)
    controlling_pid: int = getenv_int("CHUTNEY_CONTROLLING_PID", 0)
    # The path to a DNS config file for Tor Exits. If this file
    # is empty or unreadable, Tor will try 127.0.0.1:53.
    dns_conf: Optional[str] = (
        os.environ.get("CHUTNEY_DNS_CONF", "/etc/resolv.conf")
        if "CHUTNEY_DNS_CONF" in os.environ
        else None
    )
    # The phase at which this instance needs to be configured.
    config_phase: int = 1
    # The phase at which this instance needs to be launched.
    launch_phase: int = 1
    # The Sandbox torrc option value.
    # defaults to 1 on Linux, and 0 otherwise
    # Chutney users can disable the sandbox using:
    #    export CHUTNEY_TOR_SANDBOX=0
    # if it doesn't work on their version of glibc.
    sandbox: bool = getenv_bool("CHUTNEY_TOR_SANDBOX", platform.system() == "Linux")
    # Whether to enable a unix control socket (via ControlSocket in torrc)
    enable_controlsocket: bool = getenv_bool("CHUTNEY_ENABLE_CONTROLSOCKET", True)
    # Whether to use microdescriptors (via UseMicrodescriptors in torrc).
    use_microdescriptors: bool = True

    # A list of identifiers for the families that this node belongs to.
    # These identifiers are strings, and must be valid filename components.
    # Two relays are in the same family if they have any identifier in common.
    families: Optional[list[str]] = None

    # "Escape hatch" for injecting raw lines at the end of the generated torrc.
    # Generally this should only be used as a short-term workaround. For
    # long-term usage, prefer to add more-specific (and arti-compatible)
    # configuration options.
    extra_raw_torrc: str = ""

    @property
    def tor_gencert(self) -> str:
        """name or path of the tor-gencert binary (if present)"""
        return os.getenv("CHUTNEY_TOR_GENCERT", self.tor + "-gencert")

    # XXX Move template logic into template
    @property
    def owning_controller_process(self) -> str:
        """The __OwningControllerProcess torrc line,
        disabled if tor should continue after the script exits"""
        cpid = self.controlling_pid
        ocp_line = "__OwningControllerProcess %d" % (cpid)
        # if we want to leave the network running, or controlling_pid is 1
        # (or invalid)
        if (
            getenv_int("CHUTNEY_START_TIME", 0) < 0
            or getenv_int("CHUTNEY_BOOTSTRAP_TIME", 0) < 0
            or getenv_int("CHUTNEY_STOP_TIME", 0) < 0
            or cpid <= 1
        ):
            return "#" + ocp_line
        else:
            return ocp_line

    # the default resolv.conf path is set at compile time
    # there's no easy way to get it out of tor, so we use the typical value
    DEFAULT_DNS_RESOLV_CONF = Path("/etc/resolv.conf")
    # if we can't find the specified file, use this one as a substitute
    OFFLINE_DNS_RESOLV_CONF = Path("/dev/null")

    # XXX Move template logic into template
    @property
    def server_dns_resolv_conf(self) -> str:
        """the ServerDNSResolvConfFile torrc line,
        disabled if tor should use the default DNS conf.
        If the dns_conf file is missing, this option is also disabled:
        otherwise, exits would not work due to tor bug #21900."""
        my_dns_conf = self.dns_conf
        # To be set below
        dns_conf: Path

        if my_dns_conf == "":
            # if the user asked for tor's default
            return "#ServerDNSResolvConfFile using tor's compile-time default"
        elif my_dns_conf is None:
            # if there is no DNS conf file set
            debug(
                "CHUTNEY_DNS_CONF not specified, using '{}'.".format(
                    NodeConfig.DEFAULT_DNS_RESOLV_CONF
                )
            )
            dns_conf = NodeConfig.DEFAULT_DNS_RESOLV_CONF
        else:
            dns_conf = Path(my_dns_conf)
        dns_conf = dns_conf.resolve()
        # work around Tor bug #21900, where exits fail when the DNS conf
        # file does not exist, or is a broken symlink
        # (Path.exists returns False for broken symbolic links)
        if not dns_conf.exists():
            # Issue a warning so the user notices
            print(
                "CHUTNEY_DNS_CONF '{}' does not exist, using '{}'.".format(
                    dns_conf, NodeConfig.OFFLINE_DNS_RESOLV_CONF
                )
            )
            dns_conf = NodeConfig.OFFLINE_DNS_RESOLV_CONF
        return "ServerDNSResolvConfFile %s" % (dns_conf)

    def getN(self, N: int) -> list[NodeConfig]:
        """Generate 'N' duplicates of self"""
        return [copy.copy(self) for _ in range(N)]

    def specialize(self, **kwargs: Any) -> NodeConfig:
        """Return a new Node based on this node's value as its defaults,
        but with the values from 'kwargs' (if any) overriding them.

        DEPRECATED: use dataclasses.replace instead, which mypy knows how to type-check.
        """
        # mypy has a plugin to understand and properly type-check
        # dataclasses and dataclasses.replace:
        # <https://github.com/python/mypy/blob/bcd4ff231554102a6698615882074e440ebfc3c9/mypy/plugins/dataclasses.py#L202>.
        #
        # Conversely, I don't see a way to allow mypy to properly check *this*
        # function without either:
        # * spelling out the full argument list and types above, which would duplicate
        #   the class's field definitions and be a maintenance headache.
        # * creating our own mypy plugin.
        return dataclasses.replace(self, **kwargs)


@dataclasses.dataclass
class BridgeLine:
    ipaddr: str
    port: int
    fingerprint: str
    pt_transport: Option[str] = Option(None)
    pt_extra: Option[str] = Option(None)


@dataclasses.dataclass
class AuthorityLine:
    nick: str
    ipv4: str
    ipv6: Option[str]
    orport: int
    dirport: int
    v3id: str
    fingerprint: str
    fingerprint_ed25519: str
    extra_flags: list[str]
    alt_bridge_auth: bool = False
    alt_dir_auth: bool = False


KNOWN_REQUIREMENTS = {"IPV6": chutney.Host.is_ipv6_supported}


class Network(object):
    """A network of Tor nodes, plus functions to manipulate them"""

    def __init__(self) -> None:
        self._nodes: list[Node] = []
        # Keys into `KNOWN_REQUIREMENTS`
        self._requirements: list[str] = []
        self._nextnodenum = 0
        # Use the "nodes" symlink by default. This is overwritten by
        # `create_new_nodes_dir` when we configure a new network.
        self.dir: Path = get_absolute_nodes_path()

        # Whether a bridge authority has been added.
        self.hasbridgeauth = False
        # authorities: combination of AlternateDirAuthority and
        # AlternateBridgeAuthority torrc lines. there is no default for this option
        self.authorities: list[AuthorityLine] = []
        # bridges: potential Bridge descriptors in this network.
        self.bridges: list[BridgeLine] = []
        # Map from family id to FamilyId torrc line
        self.family_id_lines: dict[str, str] = dict()

        # bootstrap_time: How long in seconds we should verify (and similar
        # commands) wait for a successful outcome. We check BOOTSTRAP_TIME for
        # compatibility with old versions of test-network.sh
        self.bootstrap_time: int = getenv_int(
            "CHUTNEY_BOOTSTRAP_TIME", getenv_int("BOOTSTRAP_TIME", 60)
        )

        # orport_base, dirport_base, controlport_base, socksport_base,
        # extorport_base, ptport_base: the initial port numbers used by nodenum 0.
        # Each additional node adds 1 to the port numbers.
        self.orport_base: int = 5100
        self.dirport_base: int = 7100
        self.controlport_base: int = 8000
        self.socksport_base: int = 9000
        self.extorport_base: int = 9500
        self.ptport_base: int = 9900

    def addNode(self, config: NodeConfig) -> Node:
        """Create a node with the given config, add it to the network, and return it."""
        node = Node(self, config, self._nextnodenum)
        self._nextnodenum += 1
        self._nodes.append(node)
        if node._config.bridgeauthority:
            self.hasbridgeauth = True
        return node

    def addNodes(self, configs: List[NodeConfig]) -> List[Node]:
        """Add `nodes` to the network. `nodes` must have been created with this `Network`."""
        return [self.addNode(c) for c in configs]

    def _addRequirement(self, requirement: str) -> None:
        requirement = requirement.upper()
        if requirement not in KNOWN_REQUIREMENTS:
            raise RuntimeError(("Unrecognized requirement %r" % requirement))
        self._requirements.append(requirement)

    def move_aside_nodes_dir(self) -> None:
        """Move aside the nodes directory, if it exists and is not a link.
        Used for backwards-compatibility only: nodes is created as a link to
        a new directory with a unique name in the current implementation.
        """
        nodesdir = get_absolute_nodes_path()

        # only move the directory if it exists
        if not nodesdir.exists():
            return
        # and if it's not a link
        if nodesdir.is_symlink():
            return

        # subtract 1 second to avoid collisions and get the correct ordering
        newdir = get_new_absolute_nodes_path(time.time() - 1)

        print("NOTE: renaming '%s' to '%s'" % (nodesdir, newdir))
        nodesdir.rename(newdir)

    def create_new_nodes_dir(self) -> None:
        """Create a new directory with a unique name, and symlink it to nodes"""
        # for backwards compatibility, move aside the old nodes directory
        # (if it's not a link)
        self.move_aside_nodes_dir()

        # the unique directory we'll create
        newnodesdir = get_new_absolute_nodes_path()
        # the canonical name we'll link it to
        nodeslink = get_absolute_nodes_path()

        # this path should be unique and should not exist
        if newnodesdir.exists():
            raise RuntimeError(
                "get_new_absolute_nodes_path returned a path that exists"
            )

        # if this path exists, it must be a link
        if nodeslink.exists() and not nodeslink.is_symlink():
            raise RuntimeError(
                "get_absolute_nodes_path returned a path that exists and "
                "is not a link"
            )

        # create the new, uniquely named directory, and link it to nodes
        print("NOTE: creating '%s', linking to '%s'" % (newnodesdir, nodeslink))
        # this gets created with mode 0700, that's probably ok
        mkdir_p(newnodesdir)
        try:
            nodeslink.unlink()
        except OSError as e:
            # it's ok if the link doesn't exist, we're just about to make it
            if e.errno == errno.ENOENT:
                pass
            else:
                raise
        nodeslink.symlink_to(newnodesdir)
        self.dir = newnodesdir

    def create_family_keys(self) -> None:
        """Initialize family keys as needed for all of our nodes."""

        mkdir_p(get_familykey_path(None))
        all_family_ids = set()
        for n in self._nodes:
            if n._config.families:
                all_family_ids.update(n._config.families)
        for fid in all_family_ids:
            cmdline = [
                os.environ.get("CHUTNEY_TOR", "tor"),
                "--keygen-family",
                str(get_familykey_path(fid, ext=False)),
            ]
            output = run_tor(cmdline, tolerate_error=True)
            if "Unknown option 'keygen-family'" in output:
                print("No support for --keygen-family; using legacy families only.")
                break
            m = re.search(r"^FamilyId .*$", output, re.M)
            if not m:
                raise ChutneyError("unexpected output from tor --keygen-family")
            self.family_id_lines[fid] = m.group(0).strip() + "\n"
        with get_familykey_path("map.json", ext=False).open("w") as f:
            json.dump(self.family_id_lines, f)

    def load_family_key_ids(self) -> None:
        """Load our family key identifiers from disk."""
        family_key_dir = get_familykey_path(None)
        self.family_id_lines = json.load(family_key_dir.joinpath("map.json").open())

    def supported(self) -> None:
        """Check whether this network is supported by the set of binaries
        and host information we have, and prints the result.
        Raises `ChutneyError` if anythign is missing.
        """
        missing_any = False
        for r in self._requirements:
            if not KNOWN_REQUIREMENTS[r]():
                print(f"Can't run this network: {r} is missing.")
                missing_any = True
        for n in self._nodes:
            if not n.getBuilder().isSupported(self):
                missing_any = True

        if missing_any:
            raise ChutneyError("Missing requirements to run this network")

    def configure(self) -> None:
        """Invoked from command line: Configure and prepare the network to be
        started.
        """
        phase = CUR_CONFIG_PHASE
        if phase == 1:
            self.create_new_nodes_dir()
            self.create_family_keys()
        else:
            self.load_family_key_ids()

        network = self
        altauthlines = []
        bridgelines = []
        all_builders = [n.getBuilder() for n in self._nodes]
        builders = [
            n.getBuilder() for n in self._nodes if n._config.config_phase == phase
        ]

        # XXX don't change node names or types or count if anything is
        # XXX running!

        for b in all_builders:
            b.preConfig(network)
            auth_line = b.getAltAuthLines(self.hasbridgeauth)
            if auth_line is not None:
                altauthlines.append(auth_line)
            bridgelines.extend(b.getBridgeLines())

        self.authorities = altauthlines
        self.bridges = bridgelines

        for b in builders:
            b.config(network)

        arti_fallback_lines = []
        arti_auth_lines = []
        for auth in self.authorities:
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

        with open(os.path.join(get_absolute_nodes_path(), "arti.toml"), "w") as f:
            f.write(
                textwrap.dedent(
                    f"""
                    [storage]
                    cache_dir = "{self.dir}/arti/cache"
                    state_dir = "{self.dir}/arti/state"

                    [path_rules]
                    # These values disable enforce_distance entirely; we can replace them
                    # with something like Tor's "EnforceDistinceSubnets 0" if Arti ever
                    # implements it.
                    ipv4_subnet_family_prefix = 33
                    ipv6_subnet_family_prefix = 129

                    [address_filter]
                    # Allow the client to accept requests to connect to e.g. 127.0.0.1
                    allow_local_addrs = true
                    """
                )
            )
            f.write(
                textwrap.dedent(
                    """
                    [tor_network]
                    fallback_caches = [
                    """
                )
            )
            f.write("".join(arti_fallback_lines))
            f.write("]\n")
            f.write("authorities = [\n")
            f.write("".join(arti_auth_lines))
            f.write("]\n")

            f.write(
                textwrap.dedent(
                    """
                    [bridges]
                    enabled = "auto"
                    bridges = '''
                    """
                )
            )
            for bd in bridgelines:
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
                f.write(bridgeline)
            f.write("'''\n")

        for b in builders:
            b.postConfig(network)

    def status(self) -> bool:
        """Print how many nodes are running and how many are expected, and
        return True if all nodes are running.
        """
        cur_launch = CUR_LAUNCH_PHASE
        statuses = [
            n.getController().check(listNonRunning=True)
            for n in self._nodes
            if n._config.launch_phase == cur_launch
        ]
        n_ok = len([x for x in statuses if x])
        print("%d/%d nodes are running" % (n_ok, len(self._nodes)))
        return n_ok == len(statuses)

    def restart(self) -> None:
        """Invoked from command line: Stop and subsequently start our
        network's nodes.
        """
        self.stop()
        self.start()

    def start(self) -> None:
        """Start all our network's nodes. Raises an `ChutneyErrorGroup` on errors"""
        # format polling correctly - avoid printing a newline
        print("Starting nodes", end="")
        errs = []
        for n in self._nodes:
            if n._config.launch_phase != CUR_LAUNCH_PHASE:
                continue
            try:
                n.getController().start()
            except ChutneyError as e:
                errs.append(e)
        if len(errs) > 0:
            raise ChutneyErrorGroup("Some nodes couldn't start", errs)
        # now print a newline unconditionally - this stops poll()ing
        # output from being squashed together, at the cost of a blank
        # line in wait()ing output
        print("")

    def hup(self) -> bool:
        """Send SIGHUP to all our network's running nodes and return True on no
        errors.
        """
        print("Sending SIGHUP to nodes")
        return all([n.getController().hup() for n in self._nodes])

    def print_bootstrap_status(
        self,
        controllers: Iterable[NodeController],
        most_recent_desc_status: dict[
            str, tuple[int, Collection[str], Collection[str], str]
        ],
        elapsed: Optional[float] = None,
        msg: str = "Bootstrap in progress",
    ) -> None:
        nick_set = set()
        cons_auth_nick_set = set()
        elapsed_msg = ""
        if elapsed:
            elapsed_msg = ": {} seconds".format(int(elapsed))
        if msg:
            header = "{}{}".format(msg, elapsed_msg)
        print(header)
        print("Node status:")
        for c in controllers:
            c.check(listRunning=False, listNonRunning=True)
            nick = c.getNick()
            nick_set.add(nick)
            if c.getConsensusAuthority():
                cons_auth_nick_set.add(nick)
            pct, kwd, bmsg = c.getLastBootstrapStatus()
            # Support older tor versions without bootstrap keywords
            if not kwd:
                kwd = "None"
            print("{:13}: {:4}, {:25}, {}".format(nick, pct, kwd, bmsg))
        cache_client_nick_set = nick_set.difference(cons_auth_nick_set)
        print("Published dir info:")
        for c in controllers:
            nick = c.getNick()
            if nick in most_recent_desc_status:
                desc_status = most_recent_desc_status[nick]
                code, nodes, docs, dmsg = desc_status
                node_set = set(nodes)
                if node_set == nick_set:
                    nodes = "all nodes"
                elif node_set == cons_auth_nick_set:
                    nodes = "dir auths"
                elif node_set == cache_client_nick_set:
                    nodes = "caches and clients"
                else:
                    nodes = [node.replace("test", "") for node in nodes]
                    nodes = " ".join(sorted(nodes))
                if len(docs) >= self.getDocTypeDisplayLimit():
                    docs_string = "all formats"
                else:
                    # Fold desc_new into desc, and md_new into md
                    docs_set = set(d for d in docs)
                    if "desc_new" in docs_set:
                        docs_set.discard("desc_new")
                        docs_set.add("desc")
                    if "md_new" in docs:
                        docs_set.discard("md_new")
                        docs_set.add("md")
                    docs_string = " ".join(sorted(docs_set))
                print(
                    "{:13}: {:4}, {:25}, {:30}, {}".format(
                        nick, code, nodes, docs_string, dmsg
                    )
                )
        print()

    CHECK_NETWORK_STATUS_DELAY = 1.0
    PRINT_NETWORK_STATUS_DELAY = V3_AUTH_VOTING_INTERVAL / 2.0
    CHECKS_PER_PRINT = PRINT_NETWORK_STATUS_DELAY / CHECK_NETWORK_STATUS_DELAY

    # By default, there is no minimum start time.
    MIN_START_TIME_DEFAULT = 0

    # There are 7 v3 directory document types, but some networks only use 6,
    # because they don't have a bridge authority
    DOC_TYPE_DISPLAY_LIMIT_BRIDGEAUTH = 7
    DOC_TYPE_DISPLAY_LIMIT_NO_BRIDGEAUTH = 6

    def getDocTypeDisplayLimit(self) -> int:
        """Return the expected number of document types in this network."""
        if self.hasbridgeauth:
            return Network.DOC_TYPE_DISPLAY_LIMIT_BRIDGEAUTH
        else:
            return Network.DOC_TYPE_DISPLAY_LIMIT_NO_BRIDGEAUTH

    def getMinStartTime(self) -> int:
        """Returns the minimum start time before verifying, regardless of
        whether the network has bootstrapped, or the dir info has been
        distributed.

        The default can be overridden by the $CHUTNEY_MIN_START_TIME env
        var.
        """
        # User overrode the dynamic time
        env_min_time = getenv_int("CHUTNEY_MIN_START_TIME", None)
        if env_min_time is not None:
            return env_min_time
        return Network.MIN_START_TIME_DEFAULT

    def wait_for_bootstrap(
        self, limit_secs: int = getenv_int("CHUTNEY_START_TIME", 300)
    ) -> None:
        """
        Wait for the network to bootstrap. Raises `TimeoutException` on timeout.
        """
        print("Waiting for nodes to bootstrap...\n")
        start = time.time()
        limit = start + limit_secs
        next_print_status = start + Network.PRINT_NETWORK_STATUS_DELAY
        bootstrap_upto = CUR_LAUNCH_PHASE

        controllers = [
            n.getController()
            for n in self._nodes
            if n._config.launch_phase <= bootstrap_upto
        ]
        min_time = self.getMinStartTime()
        wait_time_list = [c.getUncheckedDirInfoWaitTime() for c in controllers]
        wait_time = max(wait_time_list)

        checks_since_last_print = 0

        while True:
            all_bootstrapped = True
            most_recent_desc_status = dict()
            for c in controllers:
                nick = c.getNick()
                c.updateLastStatus()

                if not c.isBootstrapped():
                    all_bootstrapped = False

                desc_status = c.getNodeDirInfoStatus()
                if desc_status:
                    code, nodes, docs, dmsg = desc_status
                    most_recent_desc_status[nick] = (code, nodes, docs, dmsg)
                    if code != SUCCESS_CODE:
                        all_bootstrapped = False

            now = time.time()
            elapsed = now - start
            if all_bootstrapped:
                print("Everything bootstrapped after {} sec".format(int(elapsed)))
                self.print_bootstrap_status(
                    controllers,
                    most_recent_desc_status,
                    elapsed=elapsed,
                    msg="Bootstrap finished",
                )

                # Wait for unchecked bridge or onion service dir info.
                # (See #33581 and #33609.)
                # Also used to work around a timing bug in Tor 0.3.5.
                print(
                    "Waiting {} seconds for the network to be ready...\n".format(
                        int(wait_time)
                    )
                )
                time.sleep(wait_time)
                now = time.time()
                elapsed = now - start

                # Wait for a minimum amount of run time, to avoid a race
                # condition where:
                #  - all the directory info that chutney checks is present,
                #  - but some unchecked dir info is missing
                #    (perhaps onion service descriptors, see #33609)
                #    or some other state or connection isn't quite ready, and
                #  - chutney's SOCKS connection puts tor in a failing state,
                #    which affects tor for at least 10 seconds.
                #
                # We have only seen this race condition in 0.3.5. The fixes to
                # microdescriptor downloads in 0.4.0 or 0.4.1 likely resolve
                # this issue.
                if elapsed < min_time:
                    sleep_time = min_time - elapsed
                    print(
                        (
                            "Waiting another {} seconds for legacy tor "
                            "microdesc downloads...\n"
                        ).format(int(sleep_time))
                    )
                    time.sleep(sleep_time)
                    now = time.time()
                    elapsed = now - start
                return
            if now >= limit:
                break
            if now >= next_print_status:
                if checks_since_last_print <= Network.CHECKS_PER_PRINT / 2:
                    self.print_bootstrap_status(
                        controllers,
                        most_recent_desc_status,
                        elapsed=elapsed,
                        msg="Internal timing error",
                    )
                    print(
                        "checks_since_last_print: {} (expected: {})".format(
                            checks_since_last_print, Network.CHECKS_PER_PRINT
                        )
                    )
                    print("start: {} limit: {}".format(start, limit))
                    print(
                        "next_print_status: {} now: {}".format(
                            next_print_status, time.time()
                        )
                    )
                    raise ChutneyTimeoutError()
                else:
                    self.print_bootstrap_status(
                        controllers, most_recent_desc_status, elapsed=elapsed
                    )
                    next_print_status = now + Network.PRINT_NETWORK_STATUS_DELAY
                    checks_since_last_print = 0

            time.sleep(Network.CHECK_NETWORK_STATUS_DELAY)

            # macOS Travis has some weird hangs, make sure we're not hanging
            # in this loop due to clock skew
            checks_since_last_print += 1
            if checks_since_last_print >= Network.CHECKS_PER_PRINT * 2:
                self.print_bootstrap_status(
                    controllers,
                    most_recent_desc_status,
                    elapsed=elapsed,
                    msg="Internal timing error",
                )
                print(
                    "checks_since_last_print: {} (expected: {})".format(
                        checks_since_last_print, Network.CHECKS_PER_PRINT
                    )
                )
                print("start: {} limit: {}".format(start, limit))
                print(
                    "next_print_status: {} now: {}".format(
                        next_print_status, time.time()
                    )
                )
                raise ChutneyTimeoutError()

        self.print_bootstrap_status(
            controllers,
            most_recent_desc_status,
            elapsed=elapsed,
            msg="Bootstrap failed",
        )
        raise ChutneyTimeoutError()

    # Keep in sync with ShutdownWaitLength in common.i
    SHUTDOWN_WAIT_LENGTH = 2
    # Wait for at least two event loops to elapse
    EVENT_LOOP_SLOP = 3
    # Wait for this long after signalling tor
    STOP_WAIT_TIME = SHUTDOWN_WAIT_LENGTH + EVENT_LOOP_SLOP

    def final_cleanup(
        self, wrote_dot: bool, any_tor_was_running: bool, cleanup_runfiles: bool
    ) -> None:
        """Perform final cleanup actions, based on the arguments:
        - wrote_dot: end a series of logged dots with a newline
        - any_tor_was_running: wait for STOP_WAIT_TIME for tor to stop
        - cleanup_runfiles: delete old lockfiles from crashed tors
                            rename old pid files from stopped tors
        """
        # make the output clearer by adding a newline
        if wrote_dot:
            sys.stdout.write("\n")
            sys.stdout.flush()

        # wait for tor to actually exit
        if any_tor_was_running:
            print("Waiting for nodes to cleanup and exit.")
            time.sleep(Network.STOP_WAIT_TIME)

        # clean up unwanted left-over file system state
        if cleanup_runfiles:
            controllers = [n.getController() for n in self._nodes]
            for c in controllers:
                c.cleanupRunFiles()

    def stop(self) -> None:
        """Stop our network's running tor nodes."""
        any_tor_was_running = False
        controllers = [n.getController() for n in self._nodes]
        for sig, desc in [
            (signal.SIGINT, "SIGINT"),
            (signal.SIGINT, "another SIGINT"),
            (signal.SIGKILL, "SIGKILL"),
        ]:
            print("Sending %s to nodes" % desc)
            for c in controllers:
                if c.isRunning():
                    any_tor_was_running = True
                    c.stop(sig=sig)
            print("Waiting for nodes to finish.")
            wrote_dot = False
            for _ in range(15):
                time.sleep(1)
                if all(not c.isRunning() for c in controllers):
                    self.final_cleanup(wrote_dot, any_tor_was_running, True)
                    return
                sys.stdout.write(".")
                wrote_dot = True
                sys.stdout.flush()
            for c in controllers:
                c.check(listNonRunning=False)
            # cleanup chutney's logging, but don't wait or cleanup files
            self.final_cleanup(wrote_dot, False, False)
        # wait for tor to exit, but don't cleanup logging
        self.final_cleanup(False, any_tor_was_running, True)


class CLICommands:
    """
    Methods invokable from CLI.

    All methods that don't start with `_` are invocable from the command-line.
    """

    def __init__(self, network: Network):
        self._net = network

    def print_phases(self) -> None:
        """Print the total number of phases in which the network is
        initialized, configured, or bootstrapped."""

        cfg_max = max(n._config.config_phase for n in self._net._nodes)
        launch_max = max(n._config.launch_phase for n in self._net._nodes)
        print("CHUTNEY_CONFIG_PHASES={}".format(cfg_max))
        print("CHUTNEY_LAUNCH_PHASES={}".format(launch_max))

    def final_cleanup(
        self, wrote_dot: bool, any_tor_was_running: bool, cleanup_runfiles: bool
    ) -> None:
        """Perform final cleanup actions, based on the arguments:
        - wrote_dot: end a series of logged dots with a newline
        - any_tor_was_running: wait for STOP_WAIT_TIME for tor to stop
        - cleanup_runfiles: delete old lockfiles from crashed tors
                            rename old pid files from stopped tors
        """
        self._net.final_cleanup(wrote_dot, any_tor_was_running, cleanup_runfiles)

    def create_new_nodes_dir(self) -> None:
        """Create a new directory with a unique name, and symlink it to nodes"""
        self._net.create_new_nodes_dir()

    def supported(self) -> None:
        """Check whether this network is supported by the set of binaries
        and host information we have, and prints the result.
        """
        self._net.supported()

    def configure(self) -> None:
        """Invoked from command line: Configure and prepare the network to be
        started.
        """
        self._net.configure()

    def status(self) -> bool:
        """Print how many nodes are running and how many are expected, and
        return True if all nodes are running.
        """
        return self._net.status()

    def restart(self) -> None:
        """Invoked from command line: Stop and subsequently start our
        network's nodes.
        """
        self._net.restart()

    def start(self) -> None:
        """Start all our network's nodes and return True on no errors."""
        return self._net.start()

    def hup(self) -> bool:
        """Send SIGHUP to all our network's running nodes and return True on no
        errors.
        """
        return self._net.hup()

    def wait_for_bootstrap(self) -> None:
        """Invoked from tools/test-network.sh to wait for the network to
        bootstrap.
        """
        self._net.wait_for_bootstrap()

    def stop(self) -> None:
        """Stop our network's running tor nodes."""
        self._net.stop()


def getTests() -> list[str]:
    chutney_tests_path = importlib.resources.files("chutney.network_tests")

    return [
        test.name.removesuffix(".py")
        for test in chutney_tests_path.iterdir()
        if test.name.endswith(".py") and not test.name.startswith("_")
    ]


def usage() -> str:
    return "\n".join(
        [
            "Usage: chutney {command/test} {networkfile}",
            "Known commands are: %s"
            % (" ".join(x for x in dir(CLICommands) if not x.startswith("_"))),
            "Known tests are: %s" % (" ".join(getTests())),
            "Known networks are: %s" % (" ".join(getNetworks())),
        ]
    )


def runConfigFile(verb: str, data: str) -> Optional[bool]:
    # Wrappers used from network scripts (`data`) that manipulate
    # an implicit network (`_THE_NETWORK`).
    _THE_NETWORK = Network()

    def Require(feature: str) -> None:
        _THE_NETWORK._addRequirement(feature)

    def ConfigureNodes(nodelist: list[NodeConfig]) -> None:
        for n in nodelist:
            _THE_NETWORK.addNode(n)

    def NodeWrapper(parent: Optional[NodeConfig] = None, **kwargs: Any) -> NodeConfig:
        if parent is None:
            return NodeConfig(**kwargs)
        else:
            return parent.specialize(**kwargs)

    _GLOBALS = dict(
        # Note that in the network scripts "Node" is actually a factory function
        # for creating NodeConfig.
        # TODO: Some way to make this less confusing? Maybe we can update built-in
        # networks, and only use this path for "external" network configs if we want
        # to continue supporting them.
        Node=NodeWrapper,
        Require=Require,
        ConfigureNodes=ConfigureNodes,
        torrc_option_warn_count=0,
        TORRC_OPTION_WARN_LIMIT=10,
    )

    exec(data, _GLOBALS)
    network = _THE_NETWORK

    # let's check if the verb is a valid test and run it
    if verb in getTests():
        test_module = importlib.import_module("chutney.network_tests.{}".format(verb))
        try:
            run_test = test_module.run_test
        except AttributeError as e:
            print("Error running test {!r}: {}".format(verb, e))
            return False
        try:
            run_test(network)
        except NetworkTestFailure as e:
            raise ChutneyError(f"Test '{verb}' failed") from e
        return None

    cli_cmds = CLICommands(network)

    # tell the user we don't know what their verb meant
    if not hasattr(cli_cmds, verb):
        print(usage())
        print("Error: I don't know how to %s." % verb)
        return None

    res: Optional[bool] = check_type(getattr(cli_cmds, verb)(), Optional[bool])
    return res


_NETWORKS: Traversable = (
    importlib.resources.files("chutney").joinpath("data").joinpath("networks")
)


def getNetworks() -> list[str]:
    """Get names of built-in networks."""
    return [s.name for s in _NETWORKS.iterdir()]


def getNetworkCfg(network_cfg: str) -> str:
    """Get contents of a network config script. `network_cfg` should be the name of a built-in
    network, or path to a file."""

    # First look for built-in network with matching `name`
    try:
        return _NETWORKS.joinpath(network_cfg).read_text()
    except FileNotFoundError:
        # We'll try it as a path, below.
        pass
    try:
        with open(network_cfg) as f:
            return f.read()
    except OSError as e:
        raise ChutneyError(
            f"'{network_cfg}' matches neither a built-in network name nor a readable file"
        ) from e


def main(action: str, network_cfg: str) -> None:
    """A slightly more hermetic main could be called reasonably from python

    Raises an exception derived from `ChutneyError` on failure.
    """
    network_cfg_contents = getNetworkCfg(network_cfg)
    result = runConfigFile(action, network_cfg_contents)
    if result is False:
        # TODO: eliminate this case. Have all commands
        # return a more informative error instead of `False`
        raise ChutneyError("Unspecified failure")


def __main__() -> None:
    """Raw main, suitable for use with `project.scripts` in `pyproject.toml`"""
    import traceback

    try:
        (action, network_cfg) = sys.argv[1:]
    except ValueError:
        print("Wrong number of arguments.")
        print(usage())
        sys.exit(1)
    try:
        main(action, network_cfg)
    except ChutneyError as e:
        traceback.print_exception(None, value=e, tb=None, limit=0)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    __main__()
