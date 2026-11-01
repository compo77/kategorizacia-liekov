from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "atc_groups.yaml"
)
ATC_CODE_PATTERN = re.compile(r"[A-Z]\d{2}[A-Z]{2}\d{2}")


def load_atc_config(path: Path | None = None) -> tuple[dict[str, str], str]:
    config_path = path or Path(os.environ.get("ATC_GROUPS_CONFIG", DEFAULT_CONFIG_PATH))
    try:
        with config_path.open(encoding="utf-8") as config_file:
            configuration: Any = yaml.safe_load(config_file)
    except (OSError, yaml.YAMLError) as error:
        raise RuntimeError(
            f"Nepodarilo sa načítať ATC konfiguráciu: {config_path}"
        ) from error

    if not isinstance(configuration, dict) or not isinstance(
        configuration.get("groups"), dict
    ):
        raise RuntimeError("ATC YAML musí obsahovať mapu 'groups'.")

    groups: dict[str, str] = {}
    for code, definition in configuration["groups"].items():
        if not isinstance(code, str) or not ATC_CODE_PATTERN.fullmatch(code):
            raise RuntimeError(f"Neplatný ATC kód v konfigurácii: {code!r}")
        if not isinstance(definition, dict) or not isinstance(
            definition.get("name"), str
        ):
            raise RuntimeError(
                f"ATC skupina {code} musí obsahovať textové pole 'name'."
            )
        name = definition["name"].strip()
        if not name:
            raise RuntimeError(f"ATC skupina {code} má prázdny názov.")
        groups[code] = name

    default_code = configuration.get("default")
    if not groups or default_code not in groups:
        raise RuntimeError("Predvolená ATC skupina musí byť uvedená v mape 'groups'.")
    return groups, default_code


ATC_GROUPS, DEFAULT_ATC = load_atc_config()
