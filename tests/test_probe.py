import importlib.util
from pathlib import Path

from aiohttp.test_utils import TestServer

from fake_router import FakeRouter

_spec = importlib.util.spec_from_file_location(
    "probe", Path(__file__).parents[1] / "scripts" / "probe.py"
)
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

PRIVATE = ["02:00:00:00:00", "server", "phone", "192.168.0.", "TESTSERIAL0001", "203.0.113.7"]


async def test_probe_summary_against_fake_router() -> None:
    server = TestServer(FakeRouter().app)
    await server.start_server()
    try:
        summary = await probe.run(f"{server.host}:{server.port}", "admin", "secret")
    finally:
        await server.close()
    assert "model: TG6442" in summary
    assert "devices: 3 (lan 1, wifi 1, guest_wifi 1)" in summary
    assert "downstream locked: 2/3" in summary
    assert "upstream locked: 2/2" in summary
    for value in PRIVATE:
        assert value not in summary, value
