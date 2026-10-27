#!/usr/bin/env python3
"""Validate projects.json for Winiam's Builder Tracker."""

import json
import sys
from collections import Counter
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "projects.json"
REQUIRED = (
    "name",
    "id",
    "ticker",
    "chain",
    "contract_address",
    "x_project",
    "x_founders",
    "x_team",
    "x_notable",
    "competitors",
    "category",
    "status",
    "added",
)
ALLOWED_CHAINS = {"robinhood", "solana", "arc"}


def fail(errors):
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    raise SystemExit(1)


def main():
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail([f"missing {PATH.name}"])
    except json.JSONDecodeError as exc:
        fail([f"invalid JSON: {exc}"])

    if not isinstance(data, list):
        fail(["projects.json must be a JSON array"])

    errors = []
    ids = []
    addresses = []

    for index, project in enumerate(data):
        label = f"projects[{index}]"
        if not isinstance(project, dict):
            errors.append(f"{label} must be an object")
            ids.append(None)
            addresses.append(None)
            continue

        missing = [field for field in REQUIRED if field not in project]
        if missing:
            errors.append(f"{label} missing {', '.join(missing)}")

        project_id = project.get("id")
        if isinstance(project_id, str) and project_id:
            label = project_id
        ids.append(project_id)

        address = project.get("contract_address")
        addresses.append(address)

        if project.get("chain") not in ALLOWED_CHAINS:
            errors.append(
                f"{label} chain {project.get('chain')!r} "
                f"must be one of {', '.join(sorted(ALLOWED_CHAINS))}"
            )

        competitors = project.get("competitors")
        if "competitors" in project and not isinstance(competitors, list):
            errors.append(f"{label} competitors must be a list of ids")

    for project_id, count in Counter(ids).items():
        if count > 1:
            errors.append(f"duplicate id {project_id!r} ({count})")

    for address, count in Counter(addresses).items():
        if count > 1:
            errors.append(f"duplicate contract_address {address!r} ({count})")

    known_ids = {project_id for project_id in ids if isinstance(project_id, str)}
    for project in data:
        if not isinstance(project, dict):
            continue
        competitors = project.get("competitors")
        if not isinstance(competitors, list):
            continue
        label = project.get("id", "?")
        for competitor in competitors:
            if competitor not in known_ids:
                errors.append(f"{label} competitor {competitor!r} does not exist")

    if errors:
        fail(errors)

    print(f"ok: {len(data)} projects")


if __name__ == "__main__":
    main()
