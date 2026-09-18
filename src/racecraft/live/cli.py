"""
Run the live timing recorder: `racecraft-live`.

    racecraft-live record                  # record the feed until Ctrl+C
    racecraft-live record --name baku      # name the recording
    racecraft-live status                  # what has been recorded
    racecraft-live read                    # parse the newest recording and report

A race weekend, in practice:

    racecraft-live record --name baku-2026     # leave running from FP1
    racecraft-serve                             # in another terminal

Record from the start of the first session you care about. The recording
appends across reconnections, and parsing it is cheap, so there is no cost to
starting early and every cost to starting late — the feed carries no history,
so whatever happened before the recorder started is gone.
"""

from __future__ import annotations

import argparse
import logging
import sys

from racecraft.live import feed as feed_module
from racecraft.live import recorder


def cmd_record(args) -> int:
    session = feed_module.current_session()
    if session is None:
        print("No session within four hours of now, by the published schedule.")
        print("Recording anyway — the feed is the authority, not the calendar.")
    else:
        print(f"Session: {session.year} round {session.round_number}, {session.session_name}")

    path = recorder.recording_path(args.name)
    print(f"Recording to {path}")
    if args.subscription:
        print("Using an F1 TV login. The timing stream does not need one.")
    print("Ctrl+C to stop. The recording appends, so stopping and starting again is safe.\n")
    recorder.record(path, reconnect=not args.no_reconnect, subscription=args.subscription)
    return 0


def cmd_status(args) -> int:
    found = recorder.recordings()
    if not found:
        print(f"No recordings in {recorder.LIVE_DIR}")
    else:
        print(f"{'recording':<34} {'size':>10}")
        for path in found:
            size = path.stat().st_size
            shown = f"{size / 1e6:.1f} MB" if size >= 1e6 else f"{size / 1e3:.0f} KB"
            print(f"{path.name:<34} {shown:>10}")

    # Worth printing either way: the usual question is not "what have I got"
    # but "is anything running right now".
    session = feed_module.current_session()
    print(f"\nschedule says: {session.session_name if session else 'nothing within four hours'}")
    return 0


def cmd_read(args) -> int:
    path = recorder.recording_path(args.name) if args.name else recorder.latest_recording()
    if path is None or not path.exists():
        print("No recording to read. Start one with: racecraft-live record")
        return 1

    session = feed_module.current_session()
    if session is None:
        print("Cannot tell which session this recording belongs to; the schedule has")
        print("nothing within four hours of now. Pass --year, --round and --session.")
        if not (args.year and args.round and args.session):
            return 1
    if args.year and args.round and args.session:
        session = feed_module.LiveSession(args.year, args.round, args.session)

    live = feed_module.Feed(path=path, session=session, telemetry=args.telemetry)
    try:
        tables = live.tables(force=True)
    except feed_module.NotRecording as error:
        print(f"Nothing to read: {error}")
        return 1

    print(f"\n{path.name} — {session.year} round {session.round_number}, {session.session_name}\n")
    for name, frame in sorted(tables.items()):
        print(f"  {name:<18} {len(frame):>7} rows")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    record = commands.add_parser("record", help="record the live feed until stopped")
    record.add_argument("--name", help="name the recording; defaults to the date and time")
    record.add_argument("--no-reconnect", action="store_true",
                        help="stop when the feed drops instead of reconnecting")
    record.add_argument("--subscription", action="store_true",
                        help="log in to F1 TV. Not needed: the timing stream does not check")
    record.set_defaults(handler=cmd_record)

    status = commands.add_parser("status", help="what has been recorded")
    status.set_defaults(handler=cmd_status)

    read = commands.add_parser("read", help="parse a recording and report what is in it")
    read.add_argument("--name", help="which recording; defaults to the newest")
    read.add_argument("--telemetry", action="store_true", help="include car and position data")
    read.add_argument("--year", type=int)
    read.add_argument("--round", type=int)
    read.add_argument("--session", help='FastF1 session name, e.g. "Race"')
    read.set_defaults(handler=cmd_read)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
