import configparser
import os
from dataclasses import dataclass, field
from typing import Optional

import ui
from instance_selector import select_section
from prompts import prompt_input, prompt_yes_no

CONFIG_PATH = "config.ini"


@dataclass
class RunConfig:
    api_token: str = ""
    base_url: str = ""
    source_organization_id: str = ""
    source_site_id: str = ""
    new_organization_name: str = ""
    new_superuser_details: str = ""
    site_plans: list = field(default_factory=list)
    site_clone_mode: str = "1"
    template_assignment_mode: str = "2"
    switch_template_name: Optional[str] = None
    wan_edge_template_name: Optional[str] = None
    wlan_template_name: Optional[str] = None
    rf_template_name: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "RunConfig":
        return cls(
            api_token=d.get("api_token", ""),
            base_url=d.get("base_url", ""),
            switch_template_name=d.get("switch_template_name") or None,
            wan_edge_template_name=d.get("wan_edge_template_name") or None,
            wlan_template_name=d.get("wlan_template_name") or None,
            rf_template_name=d.get("rf_template_name") or None,
        )


def validate_config_vars(cfg: RunConfig) -> None:
    missing = [k for k in ("api_token", "base_url") if not getattr(cfg, k)]
    if missing:
        raise Exception(f"Missing required config values: {', '.join(missing)}")


def manage_api_keys() -> None:
    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_PATH):
        config.read(CONFIG_PATH)

    while True:
        sections = config.sections()
        ui.section("API Key Management")
        if sections:
            ui.info("Existing profiles:")
            for idx, sec in enumerate(sections, start=1):
                base_url = config[sec].get("base_url", "")
                ui.info(f"  {idx}.  {sec}  ({base_url})")
        else:
            ui.warn("No API key profiles found.")

        ui.menu("Choose an action", [
            ("1", "Add new API key"),
            ("2", "Update existing API key"),
            ("3", "Delete API key"),
            ("4", "Done"),
        ])
        choice = prompt_input("Select option", default="1")

        if choice == "4":
            break

        if choice == "1":
            section_name = prompt_input("New section name", default="LOCAL01")
            base_url = prompt_input("Base URL", default="https://api.mist.com/api/v1")
            api_token = prompt_input("API token (input visible)")
            while not api_token:
                ui.warn("API token required.")
                api_token = prompt_input("API token (input visible)")
            config[section_name] = {
                "api_token": api_token,
                "base_url": base_url
            }
            with open(CONFIG_PATH, "w", encoding="utf-8") as file:
                config.write(file)
            ui.ok(f"Profile '{section_name}' added.")
            continue

        if choice == "2":
            if not sections:
                ui.warn("No profiles to update.")
                continue
            selection = prompt_input("Section number to update", default="1")
            try:
                index = int(selection) - 1
                section_name = sections[index]
            except (ValueError, IndexError):
                ui.warn("Invalid selection.")
                continue
            base_url = prompt_input(
                "Base URL",
                default=config[section_name].get("base_url", "https://api.mist.com/api/v1")
            )
            api_token = prompt_input("API token (input visible)")
            while not api_token:
                ui.warn("API token required.")
                api_token = prompt_input("API token (input visible)")
            config[section_name]["base_url"] = base_url
            config[section_name]["api_token"] = api_token
            with open(CONFIG_PATH, "w", encoding="utf-8") as file:
                config.write(file)
            ui.ok(f"Profile '{section_name}' updated.")
            continue

        if choice == "3":
            if not sections:
                ui.warn("No profiles to delete.")
                continue
            selection = prompt_input("Section number to delete", default="1")
            try:
                index = int(selection) - 1
                section_name = sections[index]
            except (ValueError, IndexError):
                ui.warn("Invalid selection.")
                continue
            if not prompt_yes_no(f"Delete profile '{section_name}'?", default=False):
                continue
            config.remove_section(section_name)
            with open(CONFIG_PATH, "w", encoding="utf-8") as file:
                config.write(file)
            ui.ok(f"Profile '{section_name}' deleted.")
            continue

        ui.warn("Invalid option.")


def _select_api_profile(select_title: str) -> tuple:
    if not os.path.exists(CONFIG_PATH):
        ui.warn("No API key profiles found. Please add one now.")
        manage_api_keys()

    config = configparser.ConfigParser()
    config.read(CONFIG_PATH)
    if not config.sections():
        ui.warn("No API key profiles found. Please add one now.")
        manage_api_keys()

    config.read(CONFIG_PATH)
    sections = config.sections()
    ui.info("Configured profiles:")
    for idx, sec in enumerate(sections, start=1):
        base_url = config[sec].get("base_url", "")
        ui.info(f"  {idx}.  {sec}  ({base_url})")
    print()

    if prompt_yes_no("Add or manage API key profiles?", default=False):
        manage_api_keys()

    return select_section(CONFIG_PATH, title=select_title)


def load_config(init_requested: bool = False) -> tuple:
    if init_requested or not os.path.exists(CONFIG_PATH):
        init_config_wizard()

    config = configparser.ConfigParser()
    config.read(CONFIG_PATH)
    return select_section(CONFIG_PATH)


def load_dest_config() -> tuple:
    return _select_api_profile("Select Destination Cloud Instance")


def persist_section_updates(section_name: str, updates: dict) -> None:
    config = configparser.ConfigParser()
    config.read(CONFIG_PATH)
    if section_name not in config:
        raise Exception(f"Section '{section_name}' not found in {CONFIG_PATH}.")
    for key, value in updates.items():
        config[section_name][key] = value
    with open(CONFIG_PATH, "w", encoding="utf-8") as file:
        config.write(file)


def init_config_wizard() -> None:
    ui.section("API Key Config Wizard")
    manage_api_keys()


def init_config_from_env() -> None:
    section_name = os.getenv("MIST_CONFIG_SECTION", "ENV01")
    env_config = {
        "api_token": os.getenv("MIST_API_TOKEN", "").strip(),
        "base_url": os.getenv("MIST_BASE_URL", "https://api.mist.com/api/v1").strip()
    }
    missing = [key for key, value in env_config.items() if not value]
    if missing:
        raise Exception(f"Missing required env vars for: {', '.join(missing)}")

    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_PATH):
        config.read(CONFIG_PATH)
    config[section_name] = env_config
    with open(CONFIG_PATH, "w", encoding="utf-8") as file:
        config.write(file)
    ui.ok(f"Updated {CONFIG_PATH} with section '{section_name}' from environment variables.")
