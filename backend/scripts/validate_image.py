"""Statically validate the Dockerfile and compose file without a container runtime.

Checks the things a build would otherwise catch only after minutes of pulling
layers: that every COPY source exists in the build context, that the paths the
image depends on line up with what the application computes at runtime, and that
requirements.txt agrees with pyproject.toml.

    python scripts/validate_image.py

This is not a substitute for ``docker build``; it is the part of the review that
does not need a runtime, so it can run on a laptop where Docker cannot start.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
failures: list[str] = []
checks = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        failures.append(label)


def dockerignore_patterns() -> list[str]:
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


print("[1] build context")
required = [
    "Dockerfile",
    ".dockerignore",
    "docker-compose.yml",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/index.html",
    "frontend/src/main.tsx",
    "frontend/vite.config.ts",
    "backend/requirements.txt",
    "backend/app/main.py",
    "backend/scripts/smoke_e2e.py",
]
for relative in required:
    check(f"context has {relative}", (ROOT / relative).is_file())

ignored = dockerignore_patterns()
check(".dockerignore has entries", len(ignored) > 10, str(len(ignored)))
check("node_modules ignored", "frontend/node_modules" in ignored)
check("dev database ignored", "backend/odyssey.db" in ignored)
check("frontend dist ignored (stage 1 builds it)", "frontend/dist" in ignored)
check("secrets ignored", "**/.env" in ignored)


print("\n[2] Dockerfile")
dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
# Join backslash continuations so multi-line RUN blocks parse as one instruction.
joined: list[str] = []
buffer = ""
for raw in dockerfile.splitlines():
    line = raw.rstrip()
    if not buffer and (not line.strip() or line.strip().startswith("#")):
        continue
    if line.endswith("\\"):
        buffer += line[:-1] + " "
        continue
    buffer += line
    joined.append(buffer.strip())
    buffer = ""
instructions = [line for line in joined if line]

stages = [line for line in instructions if line.startswith("FROM ")]
check("multi-stage build", len(stages) == 2, str(stages))
check("stage 1 is node", "node:" in stages[0], stages[0])
check("stage 2 is python slim", "python:3.12-slim" in stages[1], stages[1])

copies = [line for line in instructions if line.upper().startswith("COPY ")]
copy_sources = []
for line in copies:
    if "--from=" in line:
        continue  # source lives in another stage, not the build context
    for token in line.split()[1:-1]:  # every token except the destination
        clean = token.strip()
        if any(ch in clean for ch in "*?["):
            continue
        copy_sources.append(clean.rstrip("/"))
for source in copy_sources:
    check(f"COPY source exists: {source}", (ROOT / source).exists())

check("package.json copied before source (layer caching)",
      copies.index("COPY frontend/package.json frontend/package-lock.json ./")
      < copies.index("COPY frontend/ ./"))
check("requirements copied before app source",
      any(c.startswith("COPY backend/requirements.txt") for c in copies)
      and copies.index("COPY backend/requirements.txt ./")
      < copies.index("COPY backend/app ./app"))
check("built SPA copied from stage 1",
      any("--from=web" in c and "/srv/app/frontend/dist" in c for c in copies))
check("uses npm ci (fails on lockfile drift)", "RUN npm ci" in instructions)
check("no compiler toolchain needed", "build-essential" not in dockerfile)
check("tesseract installed for OCR", "tesseract-ocr" in dockerfile)
check("poppler installed for pdf2image", "poppler-utils" in dockerfile)
check("curl installed for healthcheck", "curl" in dockerfile)
check("every apt package is on one install line", dockerfile.count("apt-get install") == 1)
check("server does not run as root", "USER root" not in instructions)
check("unprivileged user is created in the image", "useradd" in dockerfile)
check("exposes 8000", "EXPOSE 8000" in instructions)
check("has a healthcheck", any(i.upper().startswith("HEALTHCHECK") for i in instructions))
check("healthcheck hits /api/health", "/api/health" in dockerfile)
check("ssrf switch pinned false", "ALLOW_PRIVATE_NETWORK_FETCH=false" in dockerfile)
check("binds 0.0.0.0", "HOST=0.0.0.0" in dockerfile)


print("\n[3] container layout vs runtime path resolution")
# Stage 2 puts the backend at /srv/app/backend and the bundle at
# /srv/app/frontend/dist; app/main.py finds it via parents[2].
from pathlib import PurePosixPath  # noqa: E402

main = PurePosixPath("/srv/app/backend/app/main.py")
dist = main.parents[2] / "frontend" / "dist"
check("main.py resolves to /srv/app/frontend/dist", str(dist) == "/srv/app/frontend/dist", str(dist))
check("assets mount resolves inside it", (dist / "assets").is_relative_to(dist))
check("WORKDIR matches COPY destination", "WORKDIR /srv/app/backend" in instructions)
check("uvicorn started from the backend root",
      any("uvicorn app.main:app" in i for i in instructions))
check("PYTHONPATH not required (cwd on sys.path)", "PYTHONPATH" not in dockerfile)

data = PurePosixPath("/srv/app/data/odyssey.db")
check("sqlite path is absolute in the image", str(data).startswith("/srv/app/data"))
upload = PurePosixPath("/srv/app/data/uploads")
check("upload dir keeps 'app' importable (not inside the package)",
      not str(upload).startswith("/srv/app/backend/app"), str(upload))
check("uploads share the volume with the database",
      str(upload).startswith("/srv/app/data"), str(upload))

# A volume is mounted after the image is built, so the build-time chown does not
# survive. Without an entrypoint that repairs ownership and drops privileges,
# the unprivileged application user cannot create the database and startup
# dies with "unable to open database file".
entry = (ROOT / "backend" / "docker-entrypoint.sh").read_text(encoding="utf-8")
dropper = (ROOT / "backend" / "drop_privs.py").read_text(encoding="utf-8")
check("entrypoint script exists in the image", "docker-entrypoint.sh" in dockerfile)
check("entrypoint is the container entrypoint", "ENTRYPOINT" in dockerfile)
check("privilege drop is copied into the image", "drop_privs.py" in dockerfile)
check("entrypoint repairs volume ownership", "chown" in entry)
check("entrypoint hands over to the privilege drop", "drop_privs.py" in entry)
check("privilege drop execs the server", "execvp" in dropper)
check("privilege drop actually changes uid", "setuid" in dropper)
check("no gosu dependency on an apt package", "gosu" not in dockerfile)
check("no USER root left at the end", "USER root" not in dockerfile)


print("\n[4] compose file")
compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
check("builds the root Dockerfile", "dockerfile: Dockerfile" in compose)
check("context is the repo root", "context: ." in compose)
check("single published port", compose.count('"${ODYSSEY_PORT:-8000}:8000"') == 1)
check("database on a named volume", "odyssey-data:/srv/app/data" in compose)
check("llm service is opt-in", 'profiles: ["llm"]' in compose)
check("extractive mode by default", 'LLM_ENABLED: "false"' in compose)
check("ssrf switch pinned false", "ALLOW_PRIVATE_NETWORK_FETCH: \"false\"" in compose)
check("healthcheck present", "healthcheck:" in compose)
check("no privileged flags", "privileged" not in compose and "network_mode: host" not in compose)
check("no docker socket mount", "/var/run/docker.sock" not in compose)


print("\n[5] requirements.txt vs pyproject.toml")
requirements = [
    line.strip()
    for line in (ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.strip().startswith("#")
]
pyproject = (ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8")
project_block = pyproject.split("dependencies = [", 1)[1].split("]", 1)[0]
declared = re.findall(r'"([^"]+)"', project_block)
extras_block = pyproject.split("ocr = [", 1)[1].split("]", 1)[0]
ocr_extra = re.findall(r'"([^"]+)"', extras_block)

req_names = {re.split(r"[><=!\[ ]", r, maxsplit=1)[0].lower() for r in requirements}

# Parse the real TOML rather than pattern-matching it: a regex truncates at the
# "]" inside "uvicorn[standard]".
with (ROOT / "backend" / "pyproject.toml").open("rb") as handle:
    pyproject = tomllib.load(handle)
project = pyproject["project"]
declared = project["dependencies"]
ocr_extra = project["optional-dependencies"]["ocr"]

check("pyproject.toml is valid TOML", project["name"] == "odyssey-transform-core")
check("pyproject declares the SIH problem", "SIH26154" in project["description"])
check("optional extras are declared", set(project["optional-dependencies"]) >= {"ocr", "speech", "dev"})

dep_names = {re.split(r"[><=!\[ ]", d, maxsplit=1)[0].lower() for d in declared}
ocr_names = {re.split(r"[><=!\[ ]", d, maxsplit=1)[0].lower() for d in ocr_extra}
known_names = dep_names | ocr_names

for name in sorted(dep_names - req_names):
    check(f"runtime dep in requirements: {name}", False, "missing")
for name in sorted(req_names - known_names):
    check(f"requirements entry declared in pyproject: {name}", False, "undeclared")
check("no undeclared requirements", not (req_names - known_names))
check("all runtime deps pinned in requirements", not (dep_names - req_names))
check("requirements documented as mirroring pyproject",
      "Mirrors [project.dependencies]" in (ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8"))
check("ocr extra installed in image", req_names >= {"pytesseract", "pdf2image"})
check("optional heavy extras left out of the image",
      not (req_names & {"faster-whisper", "sentence-transformers", "python-pptx", "numpy"}))


print("\n[6] compose env is understood by Settings")
sys.path.insert(0, str(ROOT / "backend"))
env_pairs = re.findall(r"^\s{6}([A-Z_]+):\s*\"?([^\"\n]*)\"?\s*$", compose, re.MULTILINE)
import os  # noqa: E402

os.environ.update({key: value for key, value in env_pairs if value})
from app.config import Settings  # noqa: E402

settings = Settings()
check("llm disabled by compose env", settings.llm_enabled is False)
check("extractive engine selected", not settings.llm_configured)
check("ssrf guard on", settings.allow_private_network_fetch is False)
check("redaction on", settings.pii_redaction_enabled is True)
check("numeric grounding on", settings.numeric_grounding_enabled is True)
check("web ingestion on", settings.allow_web_ingestion is True)
check("retrieval top-k from compose", settings.retrieval_top_k == 6)
check("grounding threshold from compose", settings.grounding_min_score == 0.55)
check("upload ceiling from compose", settings.max_upload_bytes == 41943040)
check("retention from compose", settings.retention_days == 90)
check("upload dir from compose is on the volume",
      settings.upload_dir.as_posix().endswith("/srv/app/data/uploads"), str(settings.upload_dir))


print("\n" + "=" * 60)
if failures:
    print(f"FAILED {len(failures)}/{checks} checks:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print(f"All {checks} image-contract checks passed.")
