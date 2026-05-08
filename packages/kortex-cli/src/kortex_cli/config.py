"""CLI configuration: profiles stored in ~/.config/kortex/config.toml."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import tomlkit
from platformdirs import user_config_dir


@dataclass(slots=True)
class CliProfile:
    name: str
    api_url: str = "http://localhost:8000"
    api_key: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None


def config_path() -> Path:
    return Path(user_config_dir("kortex", appauthor=False)) / "config.toml"


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_doc() -> tomlkit.TOMLDocument:
    path = config_path()
    if not path.exists():
        return tomlkit.document()
    with path.open("r", encoding="utf-8") as f:
        return tomlkit.parse(f.read())


def save_doc(doc: tomlkit.TOMLDocument) -> None:
    path = config_path()
    _ensure_parent(path)
    with path.open("w", encoding="utf-8") as f:
        f.write(tomlkit.dumps(doc))


def get_active_profile_name(doc: tomlkit.TOMLDocument | None = None) -> str:
    doc = doc or load_doc()
    return str(doc.get("active", "default"))


def set_active_profile(name: str) -> None:
    doc = load_doc()
    doc["active"] = name
    save_doc(doc)


def get_profile(name: str | None = None) -> CliProfile:
    doc = load_doc()
    name = name or get_active_profile_name(doc)
    profiles = doc.get("profiles", {})
    raw = dict(profiles.get(name, {})) if isinstance(profiles, dict) else {}
    api_url = (
        os.environ.get("KORTEX_API_URL")
        or raw.get("api_url")
        or "http://localhost:8000"
    )
    api_key = os.environ.get("KORTEX_API_KEY") or raw.get("api_key")
    return CliProfile(
        name=name,
        api_url=str(api_url),
        api_key=str(api_key) if api_key else None,
        access_token=str(raw["access_token"]) if "access_token" in raw else None,
        refresh_token=str(raw["refresh_token"]) if "refresh_token" in raw else None,
    )


def update_profile(profile: CliProfile) -> None:
    doc = load_doc()
    profiles = doc.setdefault("profiles", tomlkit.table())
    p = profiles.setdefault(profile.name, tomlkit.table())
    p["api_url"] = profile.api_url
    if profile.api_key is not None:
        p["api_key"] = profile.api_key
    if profile.access_token is not None:
        p["access_token"] = profile.access_token
    if profile.refresh_token is not None:
        p["refresh_token"] = profile.refresh_token
    if "active" not in doc:
        doc["active"] = profile.name
    save_doc(doc)
