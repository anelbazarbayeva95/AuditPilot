"""Unit tests for lighthouse_runner.py. No real Lighthouse/Chrome/network
required — the `npx lighthouse` subprocess is faked."""

from __future__ import annotations

import asyncio
import json
import os
import stat

import pytest

from lighthouse_runner import LighthouseError, _find_installed_chromium, run_lighthouse

GOOD_REPORT = {
    "categories": {"performance": {"score": 0.75}},
    "audits": {
        "largest-contentful-paint": {"numericValue": 2100.0},
        "cumulative-layout-shift": {"numericValue": 0.05},
        "interaction-to-next-paint": {"numericValue": 180.0},
    },
}


def _output_path_from_cmd(cmd: list[str]) -> str:
    for arg in cmd:
        if arg.startswith("--output-path="):
            return arg.split("=", 1)[1]
    raise AssertionError("no --output-path arg in command")


class _FakeProcess:
    def __init__(self, returncode: int, stderr: bytes = b"", stdout: bytes = b""):
        self.returncode = returncode
        self._stderr = stderr
        self._stdout = stdout

    async def communicate(self):
        return self._stdout, self._stderr


@pytest.fixture(autouse=True)
def _chrome_path_set(monkeypatch):
    # Bypass the Playwright-based chrome-path resolution entirely — these
    # tests only exercise the subprocess/parsing logic.
    monkeypatch.setenv("CHROME_PATH", "/usr/bin/fake-chrome")


async def test_chrome_flags_include_disable_dev_shm_usage(monkeypatch):
    # Containerized/serverless hosts often cap /dev/shm well below what
    # Chrome's renderer wants, which can crash mid-load and surface as
    # Lighthouse's misleading CHROME_INTERSTITIAL_ERROR — regression test
    # for the flag that avoids it.
    captured_cmd = {}

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        with open(_output_path_from_cmd(cmd), "w", encoding="utf-8") as f:
            json.dump(GOOD_REPORT, f)
        return _FakeProcess(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    await run_lighthouse("https://example.com")

    chrome_flags_arg = next(arg for arg in captured_cmd["cmd"] if arg.startswith("--chrome-flags="))
    assert "--disable-dev-shm-usage" in chrome_flags_arg


async def test_success_reads_report_from_output_file(monkeypatch):
    async def fake_create_subprocess_exec(*cmd, **kwargs):
        with open(_output_path_from_cmd(cmd), "w", encoding="utf-8") as f:
            json.dump(GOOD_REPORT, f)
        # Simulate npm/npx noise on stdout ahead of/instead of the report —
        # this must not affect parsing since we no longer read stdout.
        return _FakeProcess(returncode=0, stdout=b"npm notice: new version available\n")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    metrics = await run_lighthouse("https://example.com")

    assert metrics.performance_score == 75.0
    assert metrics.lcp_ms == 2100.0
    assert metrics.cls == 0.05
    assert metrics.inp_ms == 180.0


async def test_output_file_is_cleaned_up(monkeypatch):
    captured_path = {}

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        path = _output_path_from_cmd(cmd)
        captured_path["path"] = path
        with open(path, "w", encoding="utf-8") as f:
            json.dump(GOOD_REPORT, f)
        return _FakeProcess(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    await run_lighthouse("https://example.com")

    assert not os.path.exists(captured_path["path"])


async def test_nonzero_exit_raises_with_stderr(monkeypatch):
    async def fake_create_subprocess_exec(*cmd, **kwargs):
        return _FakeProcess(returncode=1, stderr=b"CHROME_PATH environment variable must be set")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(LighthouseError, match="CHROME_PATH"):
        await run_lighthouse("https://example.com")


async def test_missing_output_file_raises(monkeypatch):
    async def fake_create_subprocess_exec(*cmd, **kwargs):
        # Exits 0 but never writes the output file — e.g. Lighthouse crashed
        # after chrome-launcher succeeded but before the report was written.
        return _FakeProcess(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(LighthouseError, match="no valid report"):
        await run_lighthouse("https://example.com")


async def test_invalid_json_output_raises(monkeypatch):
    async def fake_create_subprocess_exec(*cmd, **kwargs):
        with open(_output_path_from_cmd(cmd), "w", encoding="utf-8") as f:
            f.write("not json")
        return _FakeProcess(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(LighthouseError, match="no valid report"):
        await run_lighthouse("https://example.com")


async def test_timeout_raises(monkeypatch):
    async def fake_create_subprocess_exec(*cmd, **kwargs):
        return _FakeProcess(returncode=0)

    async def fake_wait_for(coro, timeout):
        coro.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    with pytest.raises(LighthouseError, match="timed out"):
        await run_lighthouse("https://example.com")


class TestFindInstalledChromium:
    def test_finds_executable_under_browsers_path_env(self, tmp_path, monkeypatch):
        browsers_root = tmp_path / "pw-browsers"
        chrome = browsers_root / "chromium-9999" / "chrome-linux64" / "chrome"
        chrome.parent.mkdir(parents=True)
        chrome.write_text("#!/bin/sh\n")
        chrome.chmod(chrome.stat().st_mode | stat.S_IEXEC)

        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(browsers_root))

        found = _find_installed_chromium(None)
        assert found == str(chrome)

    def test_falls_back_to_expected_candidates_grandparent_dir(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
        browsers_root = tmp_path / "pw-browsers"
        chrome = browsers_root / "chromium-2222" / "chrome-linux64" / "chrome"
        chrome.parent.mkdir(parents=True)
        chrome.write_text("#!/bin/sh\n")
        chrome.chmod(chrome.stat().st_mode | stat.S_IEXEC)

        # A different (non-existent) revision than what's actually installed —
        # simulates a playwright package/browser version mismatch.
        expected = str(browsers_root / "chromium-1111" / "chrome-linux64" / "chrome")

        found = _find_installed_chromium(expected)
        assert found == str(chrome)

    def test_returns_none_when_nothing_installed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "empty"))
        assert _find_installed_chromium(None) is None
