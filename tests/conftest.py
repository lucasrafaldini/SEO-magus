"""
Shared pytest configuration: the test tiers and two run modes.

Tiers (markers registered in pytest.ini):
  unit          unmarked tests: in-process, no sockets, fast
  integration   @pytest.mark.integration: real HTTP on localhost (mock sites, RouteServer,
                fake LLM providers) or the CLI driving such a server
  benchmark     @pytest.mark.benchmark: benchmark sites and ground-truth sanity checks

Options:
  --no-network        any socket connect/bind fails with a clear message; `make test-unit`
                      uses it so a unit test that quietly starts a server is caught
  --without-networkx  hide networkx, so the pure-Python graph backend is exercised
                      (`make test-fallback`)
"""

import socket
import sys


_GUARDED = ("connect", "connect_ex", "bind")


class NetworkAccessInUnitTest(RuntimeError):
    """Raised when a test opens a socket while --no-network is active."""


def pytest_addoption(parser):
    group = parser.getgroup("seo-magus")
    group.addoption("--no-network", action="store_true",
                    help="Fail any test that opens a socket (guards the unit tier).")
    group.addoption("--without-networkx", action="store_true",
                    help="Hide networkx so the pure-Python graph backend is tested.")


def pytest_configure(config):
    if config.getoption("--without-networkx"):
        # Must happen before src.engines.link_graph is imported (at collection).
        sys.modules["networkx"] = None
    if config.getoption("--no-network"):
        originals = {name: getattr(socket.socket, name) for name in _GUARDED}
        config._seo_magus_sockets = originals  # restored in pytest_unconfigure

        def guard(name):
            def blocked(self, *args, **kwargs):
                raise NetworkAccessInUnitTest(
                    f"socket.{name}{args!r} during a --no-network run: unit tests must stay in-process. "
                    "Mark the test (or its class) with @pytest.mark.integration if it needs a local server."
                )
            return blocked

        for name in _GUARDED:
            setattr(socket.socket, name, guard(name))


def pytest_unconfigure(config):
    for name, original in getattr(config, "_seo_magus_sockets", {}).items():
        setattr(socket.socket, name, original)



# ------------------------------------------------------------ semantic context

_TIER_NAMES = {"not integration and not benchmark": "unit", "integration": "integration", "benchmark": "benchmark",
               "": "all tiers (unit + integration + benchmark)"}


def _tier_of(keywords) -> str:
    return "integration" if "integration" in keywords else ("benchmark" if "benchmark" in keywords else "unit")


def pytest_report_header(config):
    """What this run exercises, printed under the pytest banner (and kept in `make` logs)."""
    import importlib.util
    selection = (config.getoption("markexpr") or "").strip()
    tier = _TIER_NAMES.get(selection, f"custom selection (-m {selection!r})")
    if config.getoption("--without-networkx"):
        backend = "pure Python (networkx hidden by --without-networkx)"
    else:
        backend = "networkx" if importlib.util.find_spec("networkx") else "pure Python (networkx not installed)"
    guard = "ON - any socket use fails" if config.getoption("--no-network") else "off"
    return [f"seo-magus: tier = {tier} | network guard = {guard} | graph backend = {backend}"]


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Outcome per test tier, so a summary line says what was actually exercised."""
    counts = {}
    for outcome in ("passed", "failed", "error", "skipped"):
        for report in terminalreporter.stats.get(outcome, []):
            if outcome in ("passed", "failed") and getattr(report, "when", "call") != "call":
                continue                                   # setup/teardown phases of passing tests
            tier = _tier_of(getattr(report, "keywords", {}))
            counts.setdefault(tier, {}).setdefault(outcome, 0)
            counts[tier][outcome] += 1
    if not counts:
        return
    terminalreporter.section("seo-magus test tiers", sep="-")
    for tier in ("unit", "integration", "benchmark"):
        if tier in counts:
            parts = ", ".join(f"{n} {outcome}" for outcome, n in counts[tier].items())
            terminalreporter.write_line(f"{tier:<12} {parts}")
