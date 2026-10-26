"""
Racecraft.

One setting has to be made before anything imports numpy, so it is made here,
where every entry point (the app, the server, the command-line tools) starts.

numpy and scipy each bring their own OpenBLAS, which reserves working memory
for every processor thread the moment it loads: on a 12-thread machine that is
about 700 MB committed before Racecraft has done anything. Its linear algebra
here is small (a lap-effects fit is a few hundred unknowns at most), where more
threads buy nothing, so one is used. An environment that sets these first keeps
its own values.
"""

import os

for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_name, "1")
