"""Create an identifier-free, machine-checkable cloud-estate summary.

Fixture and explicit-context live modes share one sanitizer. Provider CLI responses
remain in memory; the script writes only validated aggregate counts, operational
categories, and an evidence hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DO_COMMAND_SUFFIXES: dict[str, tuple[str, ...]] = {
    "droplets": ("compute", "droplet", "list"),
    "databases": ("databases", "list"),
    "domains": ("compute", "domain", "list"),
    "firewalls": ("compute", "firewall", "list"),
    "vpcs": ("vpcs", "list"),
    "volumes": ("compute", "volume", "list"),
    "snapshots": ("compute", "snapshot", "list"),
    "projects": ("projects", "list"),
    "tags": ("compute", "tag", "list"),
    "alerts": ("monitoring", "alert", "list"),
    "uptime": ("monitoring", "uptime", "list"),
    "load_balancers": ("compute", "load-balancer", "list"),
    "certificates": ("compute", "certificate", "list"),
    "cdns": ("compute", "cdn", "list"),
    "reserved_ips": ("compute", "reserved-ip", "list"),
    "custom_images": ("compute", "image", "list-user"),
    "kubernetes_clusters": ("kubernetes", "cluster", "list"),
    "apps": ("apps", "list"),
    "registry_repositories": ("registry", "repository", "list-v2"),
}
DO_COLLECTIONS = tuple(DO_COMMAND_SUFFIXES)

DO_REGIONS = {"ams3", "atl1", "blr1", "fra1", "lon1", "nyc1", "nyc3", "sfo2", "sfo3", "sgp1", "syd1", "tor1"}
AZURE_LOCATIONS = {"francecentral", "germanywestcentral", "global", "israelcentral", "northeurope", "westeurope"}
DO_DROPLET_STATES = {"active", "archive", "new", "off"}
DO_DATABASE_STATES = {
    "creating",
    "degraded",
    "error",
    "forking",
    "maintenance",
    "migrating",
    "online",
    "resizing",
    "stopped",
}
DO_DATABASE_ENGINES = {"kafka", "mongodb", "mysql", "opensearch", "pg", "redis", "valkey"}
AZURE_SUBSCRIPTION_STATES = {"Deleted", "Disabled", "Enabled", "PastDue", "Warned"}
DO_DROPLET_SIZES = {
    "s-1vcpu-1gb",
    "s-1vcpu-2gb",
    "s-2vcpu-2gb",
    "s-2vcpu-2gb-amd",
    "s-2vcpu-4gb",
}
AZURE_RESOURCE_TYPES = {
    "Microsoft.App/containerApps",
    "Microsoft.App/jobs",
    "Microsoft.App/managedEnvironments",
    "Microsoft.Cache/redisEnterprise",
    "Microsoft.Compute/disks",
    "Microsoft.Compute/virtualMachines",
    "Microsoft.Compute/virtualMachines/extensions",
    "Microsoft.ContainerRegistry/registries",
    "Microsoft.DBforPostgreSQL/flexibleServers",
    "Microsoft.Dashboard/dashboards",
    "Microsoft.Insights/actiongroups",
    "Microsoft.Insights/components",
    "Microsoft.Insights/dataCollectionRules",
    "Microsoft.Insights/metricalerts",
    "Microsoft.Insights/scheduledqueryrules",
    "Microsoft.KeyVault/vaults",
    "Microsoft.ManagedIdentity/userAssignedIdentities",
    "Microsoft.Network/dnszones",
    "Microsoft.Network/loadBalancers",
    "Microsoft.Network/networkInterfaces",
    "Microsoft.Network/networkSecurityGroups",
    "Microsoft.Network/networkWatchers",
    "Microsoft.Network/privateDnsZones",
    "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
    "Microsoft.Network/privateEndpoints",
    "Microsoft.Network/publicIPAddresses",
    "Microsoft.Network/virtualNetworks",
    "Microsoft.OperationalInsights/workspaces",
    "Microsoft.Storage/storageAccounts",
    "Microsoft.Web/staticSites",
    "microsoft.insights/actiongroups",
}
UTC_TIMESTAMP_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$")


def build_command_plan(doctl_context: str, azure_subscription: str) -> dict[str, dict[str, list[str]]]:
    """Build the complete, fixed read-only provider command allowlist."""
    doctl = ["doctl", "--context", doctl_context]
    azure = ["az"]
    return {
        "digitalocean": {name: [*doctl, *suffix, "--output", "json"] for name, suffix in DO_COMMAND_SUFFIXES.items()},
        "azure": {
            "accounts": [
                *azure,
                "account",
                "show",
                "--subscription",
                azure_subscription,
                "--output",
                "json",
            ],
            "resource_groups": [
                *azure,
                "group",
                "list",
                "--subscription",
                azure_subscription,
                "--output",
                "json",
            ],
            "resources": [
                *azure,
                "resource",
                "list",
                "--subscription",
                azure_subscription,
                "--output",
                "json",
            ],
        },
    }


def _redact_command_plan(plan: dict[str, dict[str, list[str]]], secrets: set[str]) -> dict[str, dict[str, list[str]]]:
    return {
        provider: {
            name: ["<redacted>" if token in secrets else token for token in command]
            for name, command in commands.items()
        }
        for provider, commands in plan.items()
    }


def _require_mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _require_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a JSON array")
    return value


def _counter(values: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(value for value in values if value).items()))


def _safe_choice(value: object, allowed: set[str]) -> str:
    return value if isinstance(value, str) and value in allowed else "other"


def _safe_ttl(value: object) -> str:
    if isinstance(value, int) and 0 <= value <= 604800:
        return str(value)
    return "other"


def _require_utc_timestamp(value: object) -> str:
    if not isinstance(value, str) or not UTC_TIMESTAMP_RE.fullmatch(value):
        raise ValueError("captured_at must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("captured_at must be a UTC timestamp") from error
    if parsed.utcoffset() != UTC.utcoffset(None):
        raise ValueError("captured_at must be a UTC timestamp")
    return value


def _region_slug(item: dict[str, Any]) -> str:
    region = item.get("region")
    if isinstance(region, str):
        return region
    if isinstance(region, dict) and isinstance(region.get("slug"), str):
        return region["slug"]
    return "unknown"


def resolve_command(
    command: list[str],
    *,
    which: Callable[[str], str | None] = shutil.which,
    windows: bool = os.name == "nt",
    comspec: str | None = os.environ.get("COMSPEC"),
) -> list[str]:
    """Resolve one fixed argv command, wrapping Windows batch launchers safely."""
    if not command:
        raise ValueError("empty provider command")
    executable = which(command[0])
    if executable is None:
        raise ValueError(f"provider executable unavailable: {command[0]}")
    if windows and Path(executable).suffix.lower() in {".cmd", ".bat"}:
        if any(any(character in token for character in "&|<>^()%!\r\n") for token in command):
            raise ValueError("unsafe batch argument")
        command_line = subprocess.list2cmdline(command)
        return [comspec or "cmd.exe", "/d", "/s", "/c", command_line]
    return [executable, *command[1:]]


def _run_json_command(provider: str, name: str, command: list[str]) -> object:
    resolved_command = resolve_command(command)
    result = subprocess.run(
        resolved_command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise ValueError(f"{provider}.{name} failed with exit {result.returncode}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ValueError(f"{provider}.{name} returned malformed JSON") from error


def collect_live(
    plan: dict[str, dict[str, list[str]]],
    run_json: Callable[[str, str, list[str]], object] = _run_json_command,
    *,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Execute every allowlisted read and retain raw data only in memory."""
    timestamp = captured_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    raw: dict[str, Any] = {
        "captured_at": timestamp,
        "digitalocean": {},
        "azure": {},
    }
    for provider in ("digitalocean", "azure"):
        commands = plan.get(provider)
        if not isinstance(commands, dict) or not commands:
            raise ValueError(f"missing {provider} command plan")
        target = raw[provider]
        for name, command in commands.items():
            value = run_json(provider, name, command)
            if provider == "azure" and name == "accounts" and isinstance(value, dict):
                value = [value]
            target[name] = value
    return raw


def sanitize_capture(raw: dict[str, Any]) -> dict[str, Any]:
    """Return only counts, operational enums, and a hash of that safe summary."""
    captured_at = _require_utc_timestamp(raw.get("captured_at"))

    digitalocean = _require_mapping(raw.get("digitalocean"), "digitalocean")
    do_items = {name: _require_list(digitalocean.get(name), f"digitalocean.{name}") for name in DO_COLLECTIONS}
    droplets = [_require_mapping(item, "digitalocean.droplets item") for item in do_items["droplets"]]
    databases = [_require_mapping(item, "digitalocean.databases item") for item in do_items["databases"]]
    domains = [_require_mapping(item, "digitalocean.domains item") for item in do_items["domains"]]

    azure = _require_mapping(raw.get("azure"), "azure")
    accounts = _require_list(azure.get("accounts"), "azure.accounts")
    resource_groups = _require_list(azure.get("resource_groups"), "azure.resource_groups")
    resources = _require_list(azure.get("resources"), "azure.resources")
    account_items = [_require_mapping(item, "azure.accounts item") for item in accounts]
    group_items = [_require_mapping(item, "azure.resource_groups item") for item in resource_groups]
    resource_items = [_require_mapping(item, "azure.resources item") for item in resources]

    safe: dict[str, Any] = {
        "schema_version": 1,
        "captured_at": captured_at,
        "digitalocean": {
            "counts": {name: len(items) for name, items in do_items.items()},
            "droplet_regions": _counter([_safe_choice(_region_slug(item), DO_REGIONS) for item in droplets]),
            "droplet_sizes": _counter([_safe_choice(item.get("size_slug"), DO_DROPLET_SIZES) for item in droplets]),
            "droplet_states": _counter([_safe_choice(item.get("status"), DO_DROPLET_STATES) for item in droplets]),
            "database_engines": _counter([_safe_choice(item.get("engine"), DO_DATABASE_ENGINES) for item in databases]),
            "database_regions": _counter([_safe_choice(_region_slug(item), DO_REGIONS) for item in databases]),
            "database_states": _counter([_safe_choice(item.get("status"), DO_DATABASE_STATES) for item in databases]),
            "domain_ttls": _counter([_safe_ttl(item.get("ttl")) for item in domains]),
        },
        "azure": {
            "counts": {
                "subscriptions": len(account_items),
                "resource_groups": len(group_items),
                "resources": len(resource_items),
            },
            "subscription_states": _counter(
                [_safe_choice(item.get("state"), AZURE_SUBSCRIPTION_STATES) for item in account_items]
            ),
            "resource_group_locations": _counter(
                [_safe_choice(item.get("location"), AZURE_LOCATIONS) for item in group_items]
            ),
            "resource_types": _counter(
                [_safe_choice(item.get("type"), AZURE_RESOURCE_TYPES) for item in resource_items]
            ),
            "resource_locations": _counter(
                [_safe_choice(item.get("location"), AZURE_LOCATIONS) for item in resource_items]
            ),
        },
    }
    canonical = json.dumps(safe, sort_keys=True, separators=(",", ":")).encode("utf-8")
    safe["evidence_sha256"] = hashlib.sha256(canonical).hexdigest()
    return safe


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fixture", type=Path)
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--command-plan", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--doctl-context")
    parser.add_argument("--azure-subscription")
    args = parser.parse_args()
    if (args.command_plan or args.live) and (not args.doctl_context or not args.azure_subscription):
        parser.error("live modes require --doctl-context and --azure-subscription")
    if (args.fixture is not None or args.live) and args.output is None:
        parser.error("--fixture and --live require --output")
    return args


def main() -> int:
    args = _parse_args()
    if args.command_plan:
        plan = build_command_plan(args.doctl_context, args.azure_subscription)
        redacted = _redact_command_plan(plan, {args.doctl_context, args.azure_subscription})
        print(json.dumps(redacted, indent=2, sort_keys=True))
        return 0

    try:
        assert args.output is not None
        if args.live:
            assert args.doctl_context is not None
            assert args.azure_subscription is not None
            plan = build_command_plan(args.doctl_context, args.azure_subscription)
            raw = collect_live(plan)
        else:
            assert args.fixture is not None
            raw = _require_mapping(json.loads(args.fixture.read_text(encoding="utf-8")), "root")
        capture = sanitize_capture(raw)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise SystemExit(f"estate capture failed closed: {error}") from error

    args.output.write_text(
        json.dumps(capture, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
