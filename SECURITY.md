# Security policy

## Reporting a vulnerability

Please **do not** open a public issue for a security problem.

Report it privately through GitHub: on this repository, open the **Security** tab
and choose **Report a vulnerability**. Include what you found, how to reproduce it,
and which version (commit) you tested.

You can expect an acknowledgement within a week. Fixes go into `main`, and the
report is credited to you if you wish once the fix is out.

## Supported versions

Only the latest commit on `main` is supported. Racecraft has no releases on other
branches.

## What Racecraft is built to protect

Racecraft has no accounts, passwords or API keys and stores no personal data; it
keeps only public timing data. The local server is designed for one computer:

- it listens on `127.0.0.1` only, and answers only to this computer's host names
  (protection against DNS rebinding);
- requests that change anything (a data refresh, attaching live timing) are
  refused when they come from another website;
- every response carries a strict content security policy and anti-framing and
  anti-sniffing headers, and the page loads nothing from other sites;
- session keys are checked before they reach a query, and live recordings must sit
  in the live folder;
- the API's documentation pages are switched off.

Of most interest are ways around these: reaching the server from another device or
website when it was not opened up on purpose, reading or writing files outside the
data folder, or running code through the API or a data file.

## Out of scope

- Running the server with `--host 0.0.0.0` on an untrusted network: there is no
  login by design, and the README says so.
- The accuracy of public timing data from Formula 1 or the other sources.
- Vulnerabilities in third-party libraries with no path through Racecraft (please
  report those to the library).
