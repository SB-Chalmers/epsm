# Continuous integration

Pull requests into `dev` or `main` run one `ci` job on Python 3.13
(Node.js 22 for JavaScript). The development job checks this package and its
necessary dependencies; it does not certify the entire EPSM ecosystem.
The executable commands are in [.github/workflows/ci.yml](../.github/workflows/ci.yml).

Run **Release verification** explicitly before tagging or publishing a release,
and when a change needs the full engine, database, browser or installed-package
checks. Select one exact dependency cohort and keep that selection through the
release; do not use labels to change the tested dependencies. A merge or branch
synchronization does not publish a release or dispatch another full suite.

Do not retry dependency conflicts or missing credentials unchanged. Fix their
cause, then rerun only the affected checks. Preserve failing evidence.

See the [shared branch and CI policy](https://github.com/SB-Chalmers/epsm_development/blob/main/docs/branches-and-releases.md).
