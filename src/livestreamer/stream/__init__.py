from ..compat import str, sh, pbs_compat
from ..utils import RingBuffer
from distutils.version import LooseVersion

import os
import time
import tempfile

class StreamError(Exception):
    pass

class Stream(object):
    """
        This is a base class that should be inherited when implementing
        different stream types. Should only be used directly from plugins.
    """

    def __init__(self, session):
        self.session = session

    def open(self):
        """
            Opens a connection to the stream.
            Returns a file-like object than can be used to read data.
            Raises :exc:`StreamError` on failure.
        """
        raise NotImplementedError

class StreamProcess(Stream):
    def __init__(self, session, params={}, timeout=30):
        Stream.__init__(self, session)

        self.params = params
        self.params["_bg"] = True
        self.errorlog = self.session.options.get("errorlog")

        if not pbs_compat:
            self.fd = None
            self.timeout = timeout
            self.params["_out_bufsize"] = 8192

            if LooseVersion(sh.__version__) >= LooseVersion("1.07"):
                self.params["_no_out"] = True
                self.params["_no_pipe"] = True

    def _check_cmd(self):
        try:
            cmd = getattr(sh, self.cmd)
        except sh.CommandNotFound as err:
            raise StreamError(("Unable to find {0} command").format(str(err)))

        return cmd

    def cmdline(self):
        cmd = self._check_cmd()

        return str(cmd.bake(**self.params))

    def open(self):
        cmd = self._check_cmd()

        def out_callback(data, queue, process):
            self.fd.write(data)

        if self.errorlog:
            tmpfile = tempfile.NamedTemporaryFile(prefix="livestreamer",
                                                  suffix=".err", delete=False)
            self.params["_err"] = tmpfile
        else:
            self.params["_err"] = open(os.devnull, "wb")

        if not pbs_compat:
            self.fd = RingBuffer()
            self.params["_out"] = out_callback

        stream = cmd(**self.params)

        # Wait 0.5 seconds to see if program exited prematurely
        time.sleep(0.5)

        if pbs_compat:
            process_alive = stream.process.returncode is None
        else:
            process_alive = stream.process.alive

        if not process_alive:
            if self.errorlog:
                raise StreamError(("Error while executing subprocess, error output logged to: {0}").format(tmpfile.name))
            else:
                raise StreamError("Error while executing subprocess")

        if pbs_compat:
            return stream.process.stdout
        else:
            self.process = stream.process
            return self

    def read(self, size=0):
        if not self.fd:
            return b""

        while self.fd.length == 0 and self.process.alive:
            if self.fd.elapsed_since_write() > self.timeout:
                raise IOError("Read timeout")

            time.sleep(0.05)

        return self.fd.read(size)

    @classmethod
    def is_usable(cls, cmd):
        try:
            cmd = getattr(sh, cmd)
        except sh.CommandNotFound as err:
            return False

        return True


from .akamaihd import AkamaiHDStream
from .hls import HLSStream
from .http import HTTPStream
from .rtmpdump import RTMPStream

__all__ = ["StreamError", "Stream", "StreamProcess",
           "AkamaiHDStream", "HLSStream", "HTTPStream", "RTMPStream"]
