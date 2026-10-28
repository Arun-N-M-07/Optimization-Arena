"""Vercel deployment inputs: dependency pins, Python version and bundle exclusions must not drift or leak local files."""
import json
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _pins(name: str) -> dict[str, str]:
    out = {}
    for line in (BACKEND / name).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "-r")):
            assert "==" in line, f"{name}: {line!r} is not an exact pin"
            pkg, ver = line.split("==", 1)
            out[re.sub(r"[-_.]+", "-", pkg.split("[")[0]).lower()] = ver
    return out


def test_vercel_requirements_are_exact_pins_identical_to_the_docker_lock():
    assert _pins("requirements.txt") == _pins("requirements.lock")


def test_dev_requirements_are_exact_pins():
    assert "pytest" in _pins("requirements-dev.txt")


def test_python_version_matches_the_container_image():
    pinned = (BACKEND / ".python-version").read_text().strip()
    assert re.search(rf"^FROM python:{re.escape(pinned)}(-|$)", (BACKEND / "Dockerfile").read_text(), re.M)


def test_vercel_json_targets_the_entrypoint_and_keeps_local_files_out_of_the_bundle():
    cfg = json.loads((BACKEND / "vercel.json").read_text())
    assert (BACKEND / "app" / "main.py").is_file() and list(cfg["functions"]) == ["app/main.py"]
    fn = cfg["functions"]["app/main.py"]
    assert fn["maxDuration"] <= 300                     # Hobby ceiling; inline evaluation needs ~140 s worst case
    for must_exclude in ("tests/**", "scripts/**", ".env", ".env.*", "Dockerfile", "railway*.json", "requirements.lock"):
        assert must_exclude in fn["excludeFiles"]
    assert cfg["regions"] == fn["regions"] == ["icn1"]  # Seoul, next to the Supabase pooler (ap-northeast-2); the per-function copy is what `vercel build` records
    assert len(fn["excludeFiles"]) <= 256               # Vercel schema limit
    ignore = (BACKEND / ".vercelignore").read_text().split()
    assert ".env" in ignore and ".env.*" in ignore
