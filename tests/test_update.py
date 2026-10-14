import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

from code_shellie import cli


def test_update_flag_accepts_default_and_ref(monkeypatch):
    requested = []

    def record(ref):
        requested.append(ref)
        return True

    monkeypatch.setattr(cli, "run_update", record)
    monkeypatch.setattr(cli, "shutdown_mcp", lambda: None)

    cli.main(["--update"])
    cli.main(["--update", "1.2.3"])

    assert requested == ["main", "1.2.3"]


def test_slash_update_accepts_default_and_ref(monkeypatch):
    requested = []

    def record(ref):
        requested.append(ref)
        return True

    monkeypatch.setattr(cli, "run_update", record)

    cli.run("/update")
    cli.run("/update v1.2.3")

    assert requested == ["main", "v1.2.3"]


def test_slash_update_rejects_extra_arguments(capsys):
    cli.run("/update v1.2.3 extra")

    assert "Usage: /update [ref]" in capsys.readouterr().out


def test_failed_update_passes_ref_to_installer_and_reports_failure(monkeypatch, capsys):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == "curl":
            # The fetched installer would then fail while resolving the requested ref.
            open(args[args.index("-o") + 1], "w").close()
            return SimpleNamespace(returncode=0)
        assert args[0] == "bash"
        assert kwargs["env"]["CODESH_REF"] == "does-not-exist"
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    assert cli.run_update("does-not-exist") is False
    assert [call[0][0] for call in calls] == ["curl", "bash"]
    output = capsys.readouterr().out
    assert "Update failed" in output
    assert "Restart codesh" not in output


def test_missing_ref_download_keeps_installed_source(tmp_path):
    install_home = tmp_path / ".local/share/codesh"
    old_source = install_home / "src"
    old_source.mkdir(parents=True)
    marker = old_source / "old-install.txt"
    marker.write_text("working install", encoding="utf-8")

    # Run a copy outside a checkout so setup.sh follows its download/install path.
    installer_dir = tmp_path / "installer"
    installer_dir.mkdir()
    installer = installer_dir / "setup.sh"
    shutil.copyfile(Path(__file__).resolve().parents[1] / "setup.sh", installer)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text("#!/bin/sh\nexit 22\n", encoding="utf-8")
    curl.chmod(0o755)
    env = os.environ.copy()
    env.update({"HOME": str(tmp_path), "PATH": f"{bin_dir}:{env['PATH']}", "CODESH_REF": "does-not-exist"})

    result = subprocess.run(["bash", str(installer)], env=env, capture_output=True, text=True)

    assert result.returncode != 0
    assert marker.read_text(encoding="utf-8") == "working install"
