# Deployment run 20261005T185900Z-chat

Phase 6 chat release deployed to the existing VPS and verified through
https://getlumina.pro. Private SQLite backed up with the sqlite backup API
before any change (integrity ok). SQL0005/Django0009 applied with 8 seconds of
stopped services; release hash manifest (75 files) verified server-side.
Readiness, service resource properties, anonymous denial matrix and the
negative login path all pass through the public edge.

A pre-existing latent defect on direct internal operator routes (uncaught
TypeError for anonymous callers; failed closed as 503) was reproduced on the
old release, fixed with an anonymous guard, covered by regression tests, and
shipped in this release. No customer account, invitation or execution change;
no paid provider call. Sanitized: no keys, cookies, identities or hosts beyond
the public origin name.
