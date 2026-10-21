"""Read tlc_hr/customizing/**/*.yaml into one validated Bundle (plain Python: no Frappe, usable in CI)."""

from pathlib import Path

import yaml
from pydantic import ValidationError

from tlc_hr.contracts.customizing import Bundle, CustomizingFile

ROOT = Path(__file__).resolve().parents[2] / "customizing"
LIST_KINDS = ("roles", "custom_fields", "permissions", "email_templates", "number_cards", "charts", "shortcuts", "workspaces", "records")


class CustomizingError(Exception):
    """A YAML file that does not match the contract; the message names the file and the field."""


def read_file(path: Path) -> CustomizingFile:
    try:
        return CustomizingFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (ValidationError, yaml.YAMLError) as exc:
        raise CustomizingError(f"{path.relative_to(ROOT.parent)}: {exc}") from exc


def load_bundle(root: Path = ROOT) -> Bundle:
    files = sorted(root.rglob("*.yaml"))
    if not files:
        raise CustomizingError(f"no customizing YAML under {root}")
    merged = {kind: [] for kind in LIST_KINDS}
    merged["workflows"], merged["accounts"] = [], None
    for path in files:
        spec = read_file(path)
        for kind in LIST_KINDS:
            merged[kind] += getattr(spec, kind)
        if spec.workflow:
            merged["workflows"].append(spec.workflow)
        if spec.accounts:
            if merged["accounts"]:
                raise CustomizingError(f"{path.name}: accounts declared twice")
            merged["accounts"] = spec.accounts
    try:
        return Bundle.model_validate(merged)
    except ValidationError as exc:
        raise CustomizingError(str(exc)) from exc
