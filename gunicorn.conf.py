"""
Gunicorn configuration for the OnWatch Population Hub.

Gunicorn auto-loads this file from the working directory
(``/opt/onwatch-population`` in the systemd unit), so no ExecStart change is
needed — ``bind`` and ``workers`` still come from the unit's CLI flags, which
take precedence over anything set here.

Why this exists
---------------
A population run lasts minutes, and the UI holds a Server-Sent-Events stream
open for its whole duration. With the default **sync** worker and the default
**30s timeout**, gunicorn's arbiter decided the worker was "stuck" (it was busy
streaming progress) and killed the worker process — which also killed the
background population thread mid-step. Symptoms the operator saw:

* the UI froze partway through (often around the inquiry step),
* inquiries/cameras were created on OnWatch but left half-done / in the queue,
* those items were missing from the saved snapshot (the step died before it
  could record them), making later validation unreliable.

The fix
-------
* ``worker_class = "gthread"`` — long requests (the SSE stream) run on a thread
  while the worker keeps sending heartbeats to the arbiter, so it is no longer
  mistaken for a hung worker. Threads also let the progress stream and other
  requests be served concurrently instead of one blocking the other.
* ``timeout = 0`` — never kill a worker for a long-running request; individual
  steps still enforce their own budgets (inquiry 180s, translation 40s).
"""

worker_class = "gthread"
threads = 8
timeout = 0            # do not kill workers during long populations / SSE streams
graceful_timeout = 60
keepalive = 65
