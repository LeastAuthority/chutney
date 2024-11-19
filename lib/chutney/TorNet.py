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

from pathlib import Path
from typing import List, Optional, TypeVar, Any, Iterable, Union, Callable

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
import base64

from chutney.Debug import debug_flag, debug
from chutney.Util import getenv_int, getenv_bool, Option, OptionalConversionDescriptor
from chutney.network_tests import NetworkTestFailure
from collections.abc import Collection
from importlib.abc import Traversable
from typeguard import check_type, TypeCheckError

import chutney.Host
import chutney.Util

V3_AUTH_VOTING_INTERVAL = 20.0

_TOR_VERSIONS = None
_TORRC_OPTIONS = None

TORRC_OPTION_WARN_LIMIT = 10
torrc_option_warn_count = 0


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


def run_tor(cmdline: List[str]) -> str:
    """Run the tor command line cmdline, which must start with the path or
    name of a tor binary.

    Returns the combined stdout and stderr of the process.

    raises `ChutneyMissingBinaryException` if the tor binary is missing.
    """
    if not debug_flag:
        cmdline.append("--hush")
    try:
        res = subprocess.run(
            cmdline,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
    except FileNotFoundError as e:
        raise ChutneyMissingBinaryError.for_missing_tor("tor", cmdline) from e
    stdouterr = res.stdout
    if res.returncode != 0:
        raise ChutneyError(f"Failed to run cmdline: {cmdline}. Output: {stdouterr}")
    debug("Output for " + str(cmdline) + ":\n" + textwrap.indent(stdouterr, "    "))
    return stdouterr


def launch_process(
    cmdline: List[str], tor_name: str = "tor", stdin: Optional[int] = None
) -> subprocess.Popen[str]:
    """Launch the command line cmdline, which must start with the path or
    name of a binary. Use tor_name as the canonical name of the binary in
    logs. Pass stdin to the Popen constructor.

    Returns the Popen object for the launched process.
    """
    if tor_name == "tor":
        if not debug_flag:
            cmdline.append("--hush")
    elif tor_name == "tor-gencert":
        if debug_flag:
            cmdline.append("-v")
    else:
        raise ValueError("Unknown tor_name: '{}'".format(tor_name))
    try:
        p = subprocess.Popen(
            cmdline,
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=-1,
        )
    except FileNotFoundError as e:
        raise ChutneyMissingBinaryError.for_missing_tor(tor_name, cmdline) from e
    return p


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
def get_tor_version(tor: str) -> str:
    """Return the version of the tor binary.
    Versions are cached for each unique tor path.
    """
    cmdline = [
        tor,
        "--version",
    ]
    tor_version = run_tor(cmdline)
    # Keep only the first line of the output: since #32102 a bunch of more
    # lines have been added to --version and we only care about the first
    tor_version = tor_version.split("\n")[0]
    # clean it up a bit
    tor_version = tor_version.strip()
    tor_version = tor_version.replace("version ", "")
    tor_version = tor_version.replace(").", ")")
    # check we received a tor version, and nothing else
    assert re.match(r"^[-+.() A-Za-z0-9]+$", tor_version)

    return tor_version


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
        self.torrc: str = Option(config.torrc).unwrap(
            lambda: f"Config is missing 'torrc': {config}"
        )
        self.tag: str = Option(config.tag).unwrap(
            lambda: f"Config is missing 'tag': {config}"
        )

        # These gets set by Builder.preConfigBuild.
        # TODO: make `Optional` and init to `None`?
        # TODO: move onto the builder? Or a "builder output" field?
        self.fingerprint: Option[str] = Option(None)
        self.fingerprint_ed25519: Option[str] = Option(None)
        self.ed25519_id: Option[str] = Option(None)

        self._network = network
        self._config = config
        self._builder: Optional[LocalNodeBuilder] = None
        self._controller: Optional[LocalNodeController] = None

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
    def dirport(self) -> int:
        """DirPort that this node exposes"""
        return self._network.dirport_base + self.nodenum

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

    # TODO: return a `NodeBuilder`. Right now a lot of code implicitly assumes
    # this is a `LocalNodeBuilder`, though.
    def getBuilder(self) -> LocalNodeBuilder:
        """Return a NodeBuilder instance to set up this node (that is, to
        write all the files that need to be in place so that this
        node can be run by a NodeController).
        """
        if self._builder is None:
            self._builder = LocalNodeBuilder(self)
        return self._builder

    # TODO: return a `NodeController`. Right now a lot of code implicitly assumes
    # this is a `LocalNodeController`, though.
    def getController(self) -> LocalNodeController:
        """Return a NodeController instance to control this node (that is,
        to start it, stop it, see if it's running, etc.)
        """
        if self._controller is None:
            self._controller = LocalNodeController(self._network, self)
        return self._controller


class NodeBuilder:
    """Abstract base class.  A NodeBuilder is responsible for doing all the
    one-time prep needed to set up a node in a network.
    """

    def checkConfig(self, net: Network) -> None:
        """Try to format our torrc; raise an exception if we can't."""
        raise NotImplementedError()

    def preConfig(self, net: Network) -> None:
        """Called on all nodes before any nodes configure: generates keys as
        needed.
        """
        raise NotImplementedError()

    def config(self, net: Network) -> None:
        """Called to configure a node: creates a torrc file for it."""
        raise NotImplementedError()

    def postConfig(self, net: Network) -> None:
        """Called on each nodes after all nodes configure."""
        raise NotImplementedError()

    def isSupported(self, net: Network) -> bool:
        """Return true if this node appears to have everything it needs;
        false otherwise."""
        raise NotImplementedError()


class NodeController:
    """Abstract base class.  A NodeController is responsible for running a
    node on the network.
    """

    def check(self, listRunning: bool = True, listNonRunning: bool = False) -> bool:
        """See if this node is running, stopped, or crashed.  If it's running
        and listRunning is set, print a short statement.  If it's
        stopped and listNonRunning is set, then print a short statement.
        If it's crashed, print a statement.  Return True if the
        node is running, false otherwise.
        """
        raise NotImplementedError()

    def start(self) -> None:
        """Try to start this node, if not already running. Raises `ChutneyError` on failure."""
        raise NotImplementedError()

    def stop(self, sig: int = signal.SIGINT) -> None:
        """Try to stop this node by sending it the signal 'sig'."""
        raise NotImplementedError()


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
        # TODO: Maybe make this a (big) explicit `match` statement?
        module_name = self._node.torrc.translate({ord("."): "_", ord("-"): "_"})
        try:
            mod = importlib.import_module("chutney.torrc_templates." + module_name)
        except ModuleNotFoundError as e:
            raise ChutneyError(f"Unrecognized torrc_template {self._node.torrc}") from e
        try:
            f = check_type(getattr(mod, "format"), Callable[[Node], str])
        except (AttributeError, TypeCheckError) as e:
            raise ChutneyInternalError(
                f"module {module_name} didn't have expected format fn"
            ) from e
        # mypy still requires checking that the result is a string, even though
        # we verified the function signature.
        return check_type(f(self._node), str)

    def checkConfig(self, net: Network) -> None:
        """Try to format our torrc; raise an exception if we can't."""
        self._createTorrcFile(checkOnly=True)

    def preConfig(self, net: Network) -> None:
        """Called on all nodes before any nodes configure: generates keys and
        hidden service directories as needed.
        """
        self._makeDataDir()
        if self._node._config.authority:
            self._genAuthorityKey()
        if self._node._config.relay:
            self._genRouterKey()
        if self._node._config.hs:
            self._makeHiddenServiceDir()

    def config(self, net: Network) -> None:
        """Called to configure a node: creates a torrc file for it."""
        self._createTorrcFile()
        # self._createScripts()

    def postConfig(self, net: Network) -> None:
        """Called on each nodes after all nodes configure."""
        # self.net.addNode(self)
        pass

    def isSupported(self, net: Network) -> bool:
        """Return true if this node appears to have everything it needs;
        false otherwise."""

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
        addr = f"{self._node._config.ip}:{self._node.dirport}"
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

    def _getAltAuthLines(
        self, hasbridgeauth: bool = False
    ) -> tuple[str, tuple[str, str]]:
        """Return a set of lines to configure other nodes to use this Node as
        an authority.  For C tor, this is a combination of
        AternateDirAuthority and AlternateBridgeAuthority.  For Arti,
        this is a pair of lines to use this node as an authority and
        as a fallback.  (Arti does not automatically use authorities
        as fallbacks.)

        The answers are returned as: (tor-auth, (arti-auth, arti-fallback))

        If this node not an authority, the returned strings are empty.
        """
        if not self._node._config.authority:
            return ("", ("", ""))

        datadir = self._node.dir
        certfile = Path(datadir, "keys", "authority_certificate")
        v3id = None
        with certfile.open(mode="r") as f:
            for line in f:
                if line.startswith("fingerprint"):
                    v3id = line.split()[1].strip()
                    break

        assert v3id is not None

        if self._node._config.bridgeauthority:
            # Bridge authorities return AlternateBridgeAuthority with
            # the 'bridge' flag set.
            options = ("AlternateBridgeAuthority",)
            self._node._config.dirserver_flags += " bridge"
            arti = False
        else:
            # Directory authorities return AlternateDirAuthority with
            # the 'v3ident' flag set.
            # XXXX This next line is needed for 'bridges' but breaks
            # 'basic'
            if hasbridgeauth:
                options = ("AlternateDirAuthority",)
            else:
                options = ("DirAuthority",)
            self._node._config.dirserver_flags += " v3ident=%s" % v3id
            arti = True

        authlines = ""
        for authopt in options:
            authlines += "%s %s orport=%s" % (
                authopt,
                self._node.nick,
                self._node.orport,
            )
            # It's ok to give an authority's IPv6 address to an IPv4-only
            # client or relay: it will and must ignore it
            # and yes, the orport is the same on IPv4 and IPv6
            if self._node._config.ipv6_addr.is_some():
                authlines += " ipv6=%s:%s" % (
                    self._node._config.ipv6_addr.unwrap(),
                    self._node.orport,
                )
            authlines += " %s %s:%s %s\n" % (
                self._node._config.dirserver_flags,
                self._node._config.ip,
                self._node.dirport,
                self._node.fingerprint.unwrap(),
            )

        # generate arti configuartion if supported
        arti_lines = ("", "")
        if arti:
            addrs = '"%s:%s"' % (self._node._config.ip, self._node.orport)
            if self._node._config.ipv6_addr.is_some():
                addrs += ', "%s:%s"' % (
                    self._node._config.ipv6_addr.unwrap(),
                    self._node.orport,
                )
            elts = {
                "fp": self._node.fingerprint.unwrap().replace(" ", ""),
                "ed_fp": self._node.fingerprint_ed25519.unwrap(),
                "orports": addrs,
                "nick": self._node.nick,
                "v3id": v3id,
            }
            arti_lines = (
                (
                    "    {"
                    + f'rsa_identity = "{elts["fp"]}"'
                    + f', ed_identity = "{elts["ed_fp"]}"'
                    + f', orports = [{elts["orports"]}]'
                    + "},\n"
                ),
                (
                    "    {"
                    + f'name = "{elts["nick"]}"'
                    + f', v3ident = "{elts["v3id"]}"'
                    + "},\n"
                ),
            )
        return (authlines, arti_lines)

    def _getBridgeLines(self) -> tuple[str, str]:
        """Return tuple of string containing potential Bridge line for this Node.
        First element is the line in torrc format, and 2nd is the same line in raw/arti format.
        Non-bridge relays return ("", "").
        """
        if not self._node._config.bridge:
            return ("", "")

        if self._node._config.pt_bridge:
            port = self._node.ptport
            transport = self._node._config.pt_transport
            # TODO: can we make this just an `unwrap`?
            # Currently doing so breaks the `bridges-obfs4` network;
            extra = self._node.getController().getPtExtra().unwrap_or("")
        else:
            # the orport is the same on IPv4 and IPv6
            port = self._node.orport
            transport = ""
            extra = ""

        BRIDGE_LINE_TEMPLATE = "%s %s:%s %s %s\n"

        bridgelines = BRIDGE_LINE_TEMPLATE % (
            transport,
            self._node._config.ip,
            port,
            self._node.fingerprint.unwrap(),
            extra,
        )
        if self._node._config.ipv6_addr.is_some():
            bridgelines += BRIDGE_LINE_TEMPLATE % (
                transport,
                self._node._config.ipv6_addr.unwrap(),
                port,
                self._node.fingerprint.unwrap(),
                extra,
            )
        return (textwrap.indent(bridgelines, "Bridge "), bridgelines)


class LocalNodeController(NodeController):

    def __init__(self, network: Network, node: Node):
        NodeController.__init__(self)
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
            raise ChutneyError("Unhandled pt_transport: " + ptt)

    def getNick(self) -> str:
        """Return the nickname for this node."""
        return check_type(self._node.nick, str)

    def getBridge(self) -> int:
        """Return the bridge (relay) flag for this node."""
        try:
            return check_type(self._node._config.bridge, int)
        except KeyError:
            return 0

    def getPtExtra(self) -> Option[str]:
        """Get extra bridge info to use this node as a PT bridge.

        Returns an empty string if there is no such info (e.g. this isn't a PT bridge).
        Returns None if we *expect* there to be such info but couldn't locate it (yet).
        """
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

    def getConsensusAuthority(self) -> bool:
        """Is this node a consensus (V2 directory) authority?"""
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

    def isOnionService(self) -> bool:
        """Is this node an onion service?"""
        if self._node.tag.startswith("h"):
            return True

        try:
            return bool(check_type(self._node._config.hs, Union[int, bool]))
        except KeyError:
            return False

    # By default, there is no minimum start time.
    MIN_START_TIME_DEFAULT = 0

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
        return LocalNodeController.MIN_START_TIME_DEFAULT

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
    HS_WAIT_FOR_UNCHECKED_DIR_INFO = V3_AUTH_VOTING_INTERVAL + 10
    # We don't check for bridge descriptors before verifying.
    # See #33581.
    BRIDGE_WAIT_FOR_UNCHECKED_DIR_INFO = 10

    # Let everything propagate for another consensus period before verifying.
    LEGACY_WAIT_FOR_UNCHECKED_DIR_INFO = V3_AUTH_VOTING_INTERVAL

    def getUncheckedDirInfoWaitTime(self) -> float:
        """Returns the amount of time to wait before verifying, after the
        network has bootstrapped, and the dir info has been distributed.

        Based on whether this node has unchecked directory info, or other
        known timing issues.
        """
        if self.isOnionService():
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

    def isRunning(self, pid: Optional[int] = None) -> bool:
        """Return true iff this node is running.  (If 'pid' is provided, we
        assume that the pid provided is the one of this node.  Otherwise
        we call getPid().
        """
        if pid is None:
            pid = self.getPid()
        if pid is None:
            return False

        try:
            os.kill(pid, 0)  # "kill 0" == "are you there?"
        except OSError as e:
            if e.errno == errno.ESRCH:
                return False
            raise

        # okay, so the process exists.  Say "True" for now.
        # XXXX check if this is really tor!
        return True

    def check(self, listRunning: bool = True, listNonRunning: bool = False) -> bool:
        """See if this node is running, stopped, or crashed.  If it's running
        and listRunning is set, print a short statement.  If it's
        stopped and listNonRunning is set, then print a short statement.
        If it's crashed, print a statement.  Return True if the
        node is running, false otherwise.
        """
        # XXX Split this into "check" and "print" parts.
        pid = self.getPid()
        nick = self._node.nick
        datadir = self._node.dir
        corefile = None
        if pid:
            corefile = "core.%d" % pid
        tor_version = get_tor_version(self._node._config.tor)
        if self.isRunning(pid):
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

    def hup(self) -> bool:
        """Send a SIGHUP to this node, if it's running."""
        pid = self.getPid()
        nick = self._node.nick
        if pid is not None and self.isRunning(pid):
            print("Sending sighup to {}".format(nick))
            os.kill(pid, signal.SIGHUP)
            return True
        else:
            print("{:12} is not running".format(nick))
            return False

    def start(self) -> None:
        """Try to start this node, if not already running. Raises `ChutneyError` on failure."""

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
                raise ChutneyError(
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
                raise ChutneyError(
                    f"'{self._node.nick:12}' unexpectedly exited with code {p.returncode}."
                    + f" command '{' '.join(cmdline)}'"
                    + f" after waiting {self._node._config.poll_launch_time} seconds for launch"
                )

    def stop(self, sig: int = signal.SIGINT) -> None:
        """Try to stop this node by sending it the signal 'sig'."""
        pid = self.getPid()
        if pid is None or not self.isRunning(pid):
            print("{:12} is not running".format(self._node.nick))
            return
        os.kill(pid, sig)

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

    def updateLastOnionServiceDescStatus(self) -> None:
        """Look through the logs and cache the last onion service
        descriptor status received.
        """
        logfname = self.getLogfile(info=True)
        if not os.path.exists(logfname):
            self.most_recent_oniondesc_status = (
                LocalNodeController.MISSING_FILE_CODE,
                "no_logfile",
                "There is no logfile yet.",
            )
        percent = LocalNodeController.NO_RECORDS_CODE
        keyword = "no_message"
        message = "No onion service descriptor messages yet."
        with open(logfname, "r") as f:
            for line in f:
                m_v2 = re.search(r"Launching upload for hidden service (.*)", line)
                if m_v2:
                    percent = LocalNodeController.ONIONDESC_PUBLISHED_CODE
                    keyword = LocalNodeController.HSV2_KEYWORD
                    message = m_v2.groups()[0]
                    break
                # else check for HSv3
                m_v3 = re.search(
                    r"Service ([^\s]+ [^\s]+ descriptor of revision .*)", line
                )
                if m_v3:
                    percent = LocalNodeController.ONIONDESC_PUBLISHED_CODE
                    keyword = LocalNodeController.HSV3_KEYWORD
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

    def updateLastBootstrapStatus(self) -> None:
        """Look through the logs and cache the last bootstrap message
        received.
        """
        logfname = self.getLogfile()
        if not logfname.exists():
            self.most_recent_bootstrap_status = (
                LocalNodeController.MISSING_FILE_CODE,
                "no_logfile",
                "There is no logfile yet.",
            )
            return
        percent = LocalNodeController.NO_RECORDS_CODE
        keyword = "no_message"
        message = "No bootstrap messages yet."
        with logfname.open(mode="r") as f:
            for line in f:
                m = re.search(r"Bootstrapped (\d+)%(?: \(([^\)]*)\))?: (.*)", line)
                if m:
                    percent_s, keyword, message = m.groups()
                    percent = int(percent_s)
        self.most_recent_bootstrap_status = (percent, keyword, message)

    def getLastBootstrapStatus(self) -> tuple[int, str, str]:
        """Return the last bootstrap message fetched by
        updateLastBootstrapStatus as a 3-tuple of percentage
        complete, keyword (optional), and message.

        The return status depends on the last time updateLastStatus()
        was called; that function must be called before this one.
        """
        rv = self.most_recent_bootstrap_status
        # Caller is required to have set this via `updateLastStatus` first.
        # TODO: just call it ourselves if None, or use a default value?
        assert rv is not None
        return rv

    def updateLastStatus(self) -> None:
        """Update last messages this node has received, for use with
        isBootstrapped and the getLast* functions.
        """
        self.updateLastOnionServiceDescStatus()
        self.updateLastBootstrapStatus()

    def isBootstrapped(self) -> bool:
        """Return true iff the logfile says that this instance is
        bootstrapped.

        The return status depends on the last time updateLastStatus()
        was called; that function must be called before this one.
        """
        pct, _, _ = self.getLastBootstrapStatus()
        if pct != LocalNodeController.SUCCESS_CODE:
            return False
        if self.isOnionService():
            pct, _, _ = self.getLastOnionServiceDescStatus()
            if pct != LocalNodeController.ONIONDESC_PUBLISHED_CODE:
                return False
        return True

    # There are 7 v3 directory document types, but some networks only use 6,
    # because they don't have a bridge authority
    DOC_TYPE_DISPLAY_LIMIT_BRIDGEAUTH = 7
    DOC_TYPE_DISPLAY_LIMIT_NO_BRIDGEAUTH = 6

    def getDocTypeDisplayLimit(self) -> int:
        """Return the expected number of document types in this network."""
        if self._network.hasbridgeauth:
            return LocalNodeController.DOC_TYPE_DISPLAY_LIMIT_BRIDGEAUTH
        else:
            return LocalNodeController.DOC_TYPE_DISPLAY_LIMIT_NO_BRIDGEAUTH

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

        launch_phase = CUR_LAUNCH_PHASE

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
            raise ChutneyError(f"Invalid dir_format {dir_format}")

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
            return (LocalNodeController.MISSING_FILE_CODE, {dir_format}, "No dir file")

        dir_pattern = self.getNodeDirInfoStatusPattern(dir_format)

        line_count = 0
        with dir_path.open(mode="r") as f:
            for line in f:
                line_count = line_count + 1
                if dir_pattern:
                    m = re.search(dir_pattern, line)
                    if m:
                        return (
                            LocalNodeController.SUCCESS_CODE,
                            {dir_format},
                            "Dir info cached",
                        )

        if line_count == 0:
            return (LocalNodeController.NO_RECORDS_CODE, {dir_format}, "Empty dir file")
        elif dir_pattern is None:
            return (
                LocalNodeController.NOT_YET_IMPLEMENTED_CODE,
                {dir_format},
                "Not yet implemented",
            )
        elif line_count < 8:
            # The minimum size of the bridge networkstatus is 3 lines,
            # and the minimum size of one bridge is 5 lines
            # Let the user know the dir file is unexpectedly small
            return (
                LocalNodeController.SHORT_FILE_CODE,
                {dir_format},
                "Very short dir file",
            )
        else:
            return (
                LocalNodeController.NO_PROGRESS_CODE,
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
            elif (
                old_status_code == LocalNodeController.MISSING_FILE_CODE
                and ignore_missing
            ):
                # use the new status, which can't be MISSING_FILE_CODE,
                # because they're not equal
                dir_status = new_status
            elif (
                new_status_code == LocalNodeController.MISSING_FILE_CODE
                and ignore_missing
            ):
                # ignore the new status
                pass
            elif old_status_code == LocalNodeController.NOT_YET_IMPLEMENTED_CODE:
                # always ignore not yet implemented
                dir_status = new_status
            elif new_status_code == LocalNodeController.NOT_YET_IMPLEMENTED_CODE:
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
                raise ChutneyInternalError("Unexpectedly missing md_alts")
            md_status_code = s[0]
            if md_status_code == LocalNodeController.MISSING_FILE_CODE:
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
                    LocalNodeController.INTERNAL_ERROR_CODE,
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

    def getNodeDirInfoStatus(
        self,
    ) -> Optional[tuple[int, Collection[str], Collection[str], str]]:
        """Return a 4-tuple describing the status of this node's descriptor,
        in all the directory documents across the network.

        If this node does not have a descriptor, returns None.
        """
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
            return status_code == LocalNodeController.SUCCESS_CODE
        else:
            # Clients don't publish descriptors, so they are always ok.
            # (But we shouldn't print a descriptor status for them.)
            return None


CUR_CONFIG_PHASE: int = getenv_int("CHUTNEY_CONFIG_PHASE", 1)
CUR_LAUNCH_PHASE: int = getenv_int("CHUTNEY_LAUNCH_PHASE", 1)
CUR_BOOTSTRAP_PHASE: int = getenv_int("CHUTNEY_BOOTSTRAP_PHASE", 1)


@dataclasses.dataclass
class NodeConfig:
    """Properties of a Tor Node"""

    # Name of the template module to use to generate the config file.
    # This should be the name of a module in `chutney.torrc_templates`.
    # For backwards compatibility '-' and '.' are translated to `_`
    # when loading the module.
    # TODO: Get rid of this and build the config file based on other attributes
    # like "client", "exit", etc.
    torrc: Optional[str] = None
    # a short text string that represents the type of node.
    # Some special tag prefixes:
    # * 'h' configures it to run an onion service.
    # * 'c' and 'bc' cause the `verify` test to recognize it as a client.
    #   (as does setting the `client` attribute).
    # TODO: Get rid of these special tag meanings in favor of explicit attributes.
    tag: Optional[str] = None
    # Whether this node is configured to use a bridge.
    # (should agree with `torrc`)
    bridgeclient: bool = False
    # Whether this node is configured as a client.
    # (should agree with `torrc`)
    client: bool = False
    # Whether this node is configured as an exit.
    # (should agree with `torrc`)
    exit: bool = False

    # authority: whether a node is an authority or bridge authority
    authority: bool = False
    # bridgeauthority: whether a node is a bridge authority
    bridgeauthority: bool = False
    # relay: whether a node is a relay, exit, or bridge
    relay: bool = False
    # bridge: whether a node is a bridge
    bridge: bool = False
    # pt_bridge: whether a node is a potential bridge
    pt_bridge: bool = False
    # pt_transport: a potential bridge's transport,
    # which will be used in the Bridge torrc option
    pt_transport: str = ""
    # hs: whether a node has a hidden service
    hs: bool = False
    # hs_directory: directory (relative to datadir) to store hidden service info
    hs_directory: str = "hidden_service"
    # connlimit: value of ConnLimit torrc option
    connlimit: int = 60
    # tor: path of the tor binary
    tor: str = os.environ.get("CHUTNEY_TOR", "tor")
    # auth_cert_lifetime: lifetime of authority certs, in months
    auth_cert_lifetime: int = 12
    # ip: primary IP address (usually IPv4) to listen on
    ip: str = os.environ.get("CHUTNEY_LISTEN_ADDRESS", "127.0.0.1")
    # ipv6_addr: secondary IP address (usually IPv6) to listen on. we default to
    # ipv6_addr=None to support IPv4-only systems.
    # We use OptionalConversionDescriptor here to get `Option[str]`'s
    # enforcement for our internal usage, but allow callers to initialize and
    # assign as if it were `Optional[str]`.
    ipv6_addr: OptionalConversionDescriptor[str] = OptionalConversionDescriptor(
        default=Option(os.environ.get("CHUTNEY_LISTEN_ADDRESS_V6", None))
    )
    # Whether to disable all ipv6 functionality
    disableipv6: bool = getenv_bool("CHUTNEY_DISABLE_IPV6", False)
    # dirserver_flags: used only if authority=True
    dirserver_flags: str = "no-v2"
    # poll_launch_time: None means wait on launch (requires RunAsDaemon),
    # otherwise, poll after that many seconds (can be fractional/decimal)
    poll_launch_time: Optional[float] = None
    # poll_launch_time_default: Used when poll_launch_time is None, but
    # RunAsDaemon is not set Set low so that we don't interfere with the
    # voting interval
    poll_launch_time_default: float = 0.1
    # controlling_pid: the PID of the controlling script
    # (for __OwningControllerProcess)
    controlling_pid: int = getenv_int("CHUTNEY_CONTROLLING_PID", 0)
    # dns_conf: the path to a DNS config file for Tor Exits. If this file
    # is empty or unreadable, Tor will try 127.0.0.1:53.
    dns_conf: Optional[str] = (
        os.environ.get("CHUTNEY_DNS_CONF", "/etc/resolv.conf")
        if "CHUTNEY_DNS_CONF" in os.environ
        else None
    )
    # config_phase, launch_phase: The phase at which this instance needs to be
    # configured/launched, if we're doing multiphase configuration/launch.
    config_phase: int = 1
    launch_phase: int = 1
    # sandbox: the Sandbox torrc option value
    # defaults to 1 on Linux, and 0 otherwise
    # Chutney users can disable the sandbox using:
    #    export CHUTNEY_TOR_SANDBOX=0
    # if it doesn't work on their version of glibc.
    sandbox: bool = getenv_bool("CHUTNEY_TOR_SANDBOX", platform.system() == "Linux")
    # Whether to enable a unix control socket (via ControlSocket in torrc)
    enable_controlsocket: bool = getenv_bool("CHUTNEY_ENABLE_CONTROLSOCKET", True)

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
        """
        return dataclasses.replace(self, **kwargs)


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
        self.authorities = "AlternateDirAuthority bleargh bad torrc file!"
        # bridges: potential Bridge torrc lines for this node. there is no default
        # for this option
        self.bridges: str = "Bridge bleargh bad torrc file!"

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

    def _checkConfig(self) -> None:
        for n in self._nodes:
            n.getBuilder().checkConfig(self)

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
        network = self
        altauthlines = []
        bridgelines = []
        arti_fallback_lines = []
        arti_auth_lines = []
        arti_bridgelines = []
        all_builders = [n.getBuilder() for n in self._nodes]
        builders = [b for b in all_builders if b._node._config.config_phase == phase]
        self._checkConfig()

        # XXX don't change node names or types or count if anything is
        # XXX running!

        for b in all_builders:
            b.preConfig(network)
            tor_auth_line, (arti_fallback, arti_auth) = b._getAltAuthLines(
                self.hasbridgeauth
            )
            altauthlines.append(tor_auth_line)
            arti_fallback_lines.append(arti_fallback)
            arti_auth_lines.append(arti_auth)
            tor_bridgeline, arti_bridgeline = b._getBridgeLines()
            bridgelines.append(tor_bridgeline)
            arti_bridgelines.append(arti_bridgeline)

        self.authorities = "".join(altauthlines)
        self.bridges = "".join(bridgelines)

        for b in builders:
            b.config(network)

        with open(os.path.join(get_absolute_nodes_path(), "arti.toml"), "w") as f:
            f.write(
                """[storage]
cache_dir = "{path}/arti/cache"
state_dir = "{path}/arti/state"

[path_rules]
# These values disable enforce_distance entirely; we can replace them
# with something like Tor's "EnforceDistinceSubnets 0" if Arti ever
# implements it.
ipv4_subnet_family_prefix = 33
ipv6_subnet_family_prefix = 129

[address_filter]
# Allow the client to accept requests to connect to e.g. 127.0.0.1
allow_local_addrs = true

""".format(
                    path=self.dir
                )
            )
            f.write(
                """[tor_network]
fallback_caches = [
"""
            )
            f.write("".join(arti_fallback_lines))
            f.write("]\n")
            f.write("authorities = [\n")
            f.write("".join(arti_auth_lines))
            f.write("]\n")

            f.write(
                """[bridges]
enabled = "auto"
bridges = '''
"""
            )
            f.write("".join(arti_bridgelines))
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
        controllers: Iterable[LocalNodeController],
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
                if len(docs) >= c.getDocTypeDisplayLimit():
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
        min_time_list = [c.getMinStartTime() for c in controllers]
        min_time = max(min_time_list)
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
                    if code != LocalNodeController.SUCCESS_CODE:
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

        # check for stale lock files when Tor crashes
        # move aside old pid files after Tor stops running
        if cleanup_runfiles:
            controllers = [n.getController() for n in self._nodes]
            for c in controllers:
                c.cleanup_lockfile()
                c.cleanup_pidfile()

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
