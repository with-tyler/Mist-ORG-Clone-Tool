import ui


def prompt_input(label, default=None, allow_empty=False):
    return ui.ask(label, default=default, allow_empty=allow_empty)


def prompt_yes_no(label, default=True):
    return ui.ask_yn(label, default=default)


def select_from_list(items, item_label, name_key="name", id_key="id"):
    if not items:
        return None
    ui.section(f"Select {item_label.title()}")
    ui.numbered_list(items, name_key=name_key, id_key=id_key)
    selection = prompt_input("Enter number (or press Enter to skip)", default="", allow_empty=True)
    if not selection:
        return None
    try:
        index = int(selection) - 1
        if 0 <= index < len(items):
            return items[index].get(id_key)
    except ValueError:
        pass
    ui.warn("Invalid selection — skipping.")
    return None


def select_name_from_list(items, item_label, name_key="name", id_key="id"):
    if not items:
        return None
    ui.section(f"Select {item_label.title()}")
    ui.numbered_list(items, name_key=name_key, id_key=id_key)
    selection = prompt_input("Enter number (or press Enter to skip)", default="", allow_empty=True)
    if not selection:
        return None
    try:
        index = int(selection) - 1
        if 0 <= index < len(items):
            return items[index].get(name_key)
    except ValueError:
        pass
    ui.warn("Invalid selection — skipping.")
    return None
