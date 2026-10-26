"""
Racecraft as a desktop application: one icon, its own window, nothing to run.

`main.main` starts the API on a free port of its own, opens the interface in a
native window (WebView2, through pywebview), and keeps the lake current while
the window is open. Closing the window stops all of it.
"""
