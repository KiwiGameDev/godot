import argparse
import os
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
CUSTOM_TARGETS_FILE = PROJECT_ROOT / ".idea" / "customTargets.xml"
EXTERNAL_TOOLS_FILE = PROJECT_ROOT / ".idea" / "tools" / "External Tools.xml"


def expand_clion_macros(value: str) -> str:
    return (
        value
        .replace("$ProjectFileDir$", str(PROJECT_ROOT))
        .replace("$PROJECT_DIR$", str(PROJECT_ROOT))
    )


def parse_external_tools() -> dict[str, dict[str, str]]:
    if not EXTERNAL_TOOLS_FILE.exists():
        raise FileNotFoundError(f"Missing file: {EXTERNAL_TOOLS_FILE}")

    root = ET.parse(EXTERNAL_TOOLS_FILE).getroot()
    tools = {}

    for tool in root.findall("tool"):
        name = tool.attrib.get("name")
        exec_node = tool.find("exec")

        if not name or exec_node is None:
            continue

        command = None
        parameters = ""
        working_directory = str(PROJECT_ROOT)

        for option in exec_node.findall("option"):
            option_name = option.attrib.get("name")
            option_value = option.attrib.get("value", "")

            if option_name == "COMMAND":
                command = expand_clion_macros(option_value)
            elif option_name == "PARAMETERS":
                parameters = expand_clion_macros(option_value)
            elif option_name == "WORKING_DIRECTORY":
                working_directory = expand_clion_macros(option_value)

        if command:
            tools[name] = {
                "command": command,
                "parameters": parameters,
                "working_directory": working_directory,
            }

    return tools


def parse_clion_build_targets() -> list[dict[str, str]]:
    if not CUSTOM_TARGETS_FILE.exists():
        raise FileNotFoundError(f"Missing file: {CUSTOM_TARGETS_FILE}")

    root = ET.parse(CUSTOM_TARGETS_FILE).getroot()
    targets = []

    manager = root.find("./component[@name='CLionExternalBuildManager']")
    if manager is None:
        return targets

    for target in manager.findall("target"):
        target_name = target.attrib.get("name", "<unnamed target>")

        for configuration in target.findall("configuration"):
            configuration_name = configuration.attrib.get("name", target_name)
            build = configuration.find("build")

            if build is None:
                continue

            tool = build.find("tool")
            if tool is None:
                continue

            action_id = tool.attrib.get("actionId", "")

            prefix = "Tool_External Tools_"
            if not action_id.startswith(prefix):
                continue

            external_tool_name = action_id[len(prefix):]

            targets.append({
                "target_name": target_name,
                "configuration_name": configuration_name,
                "external_tool_name": external_tool_name,
            })

    return targets


def run_command(
        target_name: str,
        configuration_name: str,
        tool_name: str,
        command: str,
        parameters: str,
        working_directory: str,
        dry_run: bool,
) -> int:
    args = [command]

    if parameters:
        args.extend(shlex.split(parameters, posix=os.name != "nt"))

    print()
    print("=" * 100)
    print(f"Target:        {target_name}")
    print(f"Configuration: {configuration_name}")
    print(f"External tool: {tool_name}")
    print(f"Working dir:   {working_directory}")
    print(f"Command:       {' '.join(shlex.quote(arg) for arg in args)}")
    print("=" * 100)

    if dry_run:
        return 0

    process = subprocess.run(args, cwd=working_directory)
    return process.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build all CLion External Build configurations configured in .idea/customTargets.xml."
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Build only configurations whose target/config/tool name contains this text. Can be passed multiple times.",
    )
    parser.add_argument(
        "--skip",
        action="append",
        default=[],
        help="Skip configurations whose target/config/tool name contains this text. Can be passed multiple times.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue building remaining configurations if one build fails.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing them.",
    )

    args = parser.parse_args()

    external_tools = parse_external_tools()
    targets = parse_clion_build_targets()

    if not targets:
        print("No CLion External Build targets found.")
        return 1

    failed = []

    for target in targets:
        searchable_name = " ".join([
            target["target_name"],
            target["configuration_name"],
            target["external_tool_name"],
        ]).lower()

        if args.only and not any(value.lower() in searchable_name for value in args.only):
            continue

        if args.skip and any(value.lower() in searchable_name for value in args.skip):
            continue

        tool_name = target["external_tool_name"]
        tool = external_tools.get(tool_name)

        if tool is None:
            print(f"Missing External Tool definition for: {tool_name}", file=sys.stderr)
            failed.append(target["configuration_name"])

            if not args.continue_on_error:
                return 1

            continue

        return_code = run_command(
            target_name=target["target_name"],
            configuration_name=target["configuration_name"],
            tool_name=tool_name,
            command=tool["command"],
            parameters=tool["parameters"],
            working_directory=tool["working_directory"],
            dry_run=args.dry_run,
        )

        if return_code != 0:
            failed.append(target["configuration_name"])
            print(f"Build failed: {target['configuration_name']} exit code {return_code}", file=sys.stderr)

            if not args.continue_on_error:
                return return_code

    if failed:
        print()
        print("Failed configurations:")
        for name in failed:
            print(f"  - {name}")
        return 1

    print()
    print("All selected CLion build configurations completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
