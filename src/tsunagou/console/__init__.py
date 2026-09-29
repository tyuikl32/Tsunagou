"""The local console: one same-origin service in front of the daemons.

A daemon serves exactly one project and expects a bearer control token on most of
its reads. A browser cannot hold that token, cannot talk to several daemons at
once, and cannot read a file. The console exists for those three reasons and
nothing else:

* it hands the browser the page it already has, from ``web/``;
* it forwards ``/api/v1/...`` to the daemon that owns the requested project,
  adding the control token **on the server side**, so the token never reaches the
  page;
* it owns the handful of facts that belong to the machine rather than to a
  project (which projects exist, what the person calls their agents).

It never reads a project's database: everything project-scoped goes through the
daemon's own HTTP API, so the console cannot drift from the daemon's rules.
"""
