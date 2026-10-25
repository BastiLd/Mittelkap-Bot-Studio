"""Build two allowlisted code-only ZIPs. Never read private data or credentials."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent.parent
ASSET_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ttf", ".otf", ".woff", ".woff2"}
STATIC_TYPES = ASSET_TYPES | {".html", ".css", ".js", ".json", ".ico", ".txt"}
FONT_FILES = ("Archivo.ttf", "Roboto.ttf", "RobotoMono.ttf", "LICENSE-Archivo.txt", "LICENSE-Roboto.txt", "LICENSE-RobotoMono.txt", "SOURCES.md")


def files(folder, extensions):
    return sorted(p for p in folder.rglob("*") if p.is_file() and not p.is_symlink()
                  and p.suffix.lower() in extensions and not any(part.startswith(".") or part == "__pycache__" for part in p.relative_to(folder).parts))


def packlists(root=ROOT):
    root = Path(root)
    web_folder = root / ("Dashboard" if (root / "Dashboard").is_dir() else "Webseite")
    deploy_folder = root / ("deployment" if (root / "deployment").is_dir() else "Allgemein")
    manager = {}
    for name in ("Jarvis", "Ultron"):
        for leaf in ("bot.py", "diagnose.py", "config.json"):
            manager[f"{name}/{leaf}"] = root / name / leaf
        for path in files(root / name / "botapp", {".py"}):
            manager[path.relative_to(root).as_posix()] = path
        manager[f"{name}/botapp/editor_catalog.json"] = root / name / "botapp" / "editor_catalog.json"
        for path in files(root / name / "assets", ASSET_TYPES):
            if path.relative_to(root / name / "assets").parts[0] != "fonts":
                manager[path.relative_to(root).as_posix()] = path
        for leaf in FONT_FILES:
            manager[f"{name}/assets/fonts/{leaf}"] = root / name / "assets" / "fonts" / leaf
    manager["Dashboard/server.py"] = web_folder / "server.py"
    frontend = {"index.html": web_folder / "static" / "index.html"}
    for path in files(web_folder / "static", STATIC_TYPES):
        relative = path.relative_to(web_folder).as_posix()
        frontend[relative] = path
        manager["Dashboard/" + relative] = path
    for name, source in (("start.py", "start.py"), ("requirements.txt", "requirements.txt"),
                         ("README_SERVER.md", "README.md"), ("Manager.env.example", "Manager.env.example")):
        manager[name] = deploy_folder / source
    manager["STUDIO_V4.md"] = root / "STUDIO_V4.md" if (root / "STUDIO_V4.md").is_file() else deploy_folder / "STUDIO_V4.md"
    return {"Mittelkap-Manager.zip": manager, "Mittelkap-WebHafen.zip": frontend}


def build(output, root=ROOT):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for filename, entries in packlists(root).items():
        target = output / filename
        temporary = target.with_suffix(".zip.tmp")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name, path in sorted(entries.items()):
                if not path.is_file() or path.is_symlink():
                    raise ValueError("Erforderliche Paketdatei fehlt oder ist ein Symlink: " + name)
                archive.write(path, name)
        temporary.replace(target)
        manifest[filename] = {"bytes": target.stat().st_size,
                              "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                              "files": sorted(entries)}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Codepakete ohne Tokens, Konten, Datenbanken oder Logs bauen.")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "dist")
    args = parser.parse_args()
    for filename, item in build(args.output_dir).items():
        print(f"{filename}: {item['bytes']} Bytes, {len(item['files'])} Dateien; SHA-256 {item['sha256']}")
