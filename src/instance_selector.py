import configparser
import ui


def display_help() -> None:
    """Display help information for the user."""
    ui.section("Help")
    ui.info("This tool selects a Cloud Instance (API key profile) from config.ini.")
    ui.info("")
    ui.info("  • A numbered list of configured instances will be shown.")
    ui.info("  • Enter the number of the instance you want to use.")
    ui.info("  • Type  help  at any time to show this guide again.")
    ui.info("  • Type  exit  to quit the program.")


def select_section(config_file: str = "config.ini",
                   title: str = "Select Cloud Instance") -> tuple[str, dict]:
    """
    Interactively choose a Cloud Instance section from the config file.

    Args:
        config_file: Path to the configuration file.
        title:       Section header displayed to the user.

    Returns:
        (section_name, config_dict) for the chosen instance.
    """
    config = configparser.ConfigParser()
    config.read(config_file)

    sections = config.sections()

    if not sections:
        raise Exception("No instances found in the configuration file.")

    while True:
        ui.section(title)
        ui.numbered_list([{"name": s, "id": None} for s in sections], name_key="name", id_key="id")
        print()
        ui.info("Type a number to select, 'help' for guidance, or 'exit' to quit.")

        raw = input(_prompt_str("Instance number")).strip()

        if raw.lower() == "help":
            display_help()
            continue

        if raw.lower() == "exit":
            ui.info("Goodbye!")
            exit()

        try:
            idx = int(raw) - 1
            if 0 <= idx < len(sections):
                chosen = sections[idx]
                ui.ok(f"Selected instance: {chosen}")
                return chosen, {key: config[chosen][key] for key in config[chosen]}
            ui.warn("Invalid number — please choose from the list above.")
        except ValueError:
            ui.warn("Please enter a valid number, 'help', or 'exit'.")


def _prompt_str(label: str) -> str:
    """Return a consistently styled input prompt string (no trailing newline)."""
    try:
        from ui import _c, _CYAN, _BOLD
        return f"\n  {_c(_CYAN, '?')} {_c(_BOLD, label)}\n    → "
    except Exception:
        return f"\n  ? {label}\n    → "
