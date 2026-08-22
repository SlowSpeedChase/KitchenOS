"""When this process started.

The API runs as a long-lived LaunchAgent that imports ``lib/*`` once and holds
the modules for its whole life, so editing code on disk does not reach the
running server. Detecting that needs one fact Python does not otherwise expose
portably: **when this process began**, as opposed to when any particular module
happened to get imported.

It has to live in its own module, imported eagerly by ``api_server`` at startup,
for a reason that is easy to get wrong: ``lib/health.py`` and
``lib/health_assertions.py`` are both imported *lazily* inside their routes, so
a timestamp captured at their import is the time of the first health request —
which is always newer than the code and would report a stale server as fresh.
Capturing it here, from the one module the server imports before it serves
anything, is what makes the comparison mean what it says.

No ``psutil``: the OS process-start time would be more direct, but it is not in
this project's dependencies and macOS has no ``/proc``. Import time of the first
module is within milliseconds of process start, which is far below the
resolution any staleness question needs.
"""

from __future__ import annotations

import time

#: Unix timestamp captured when this module is first imported — i.e. at server
#: startup, because ``api_server`` imports it at module scope. Compared against
#: source-file mtimes by ``health_assertions.check_server_freshness``.
BOOT_TIME: float = time.time()
