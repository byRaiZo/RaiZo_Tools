from pathlib import Path

from core import pbo_context_menu


def test_context_menu_command_uses_saved_builder_options() -> None:
    command = pbo_context_menu.command_line(executable=Path(r"C:\Program Files\RaiZo Tools\RaiZoTools.exe"))

    assert command.startswith('"C:\\Program Files\\RaiZo Tools\\RaiZoTools.exe"')
    assert '--pack-folder "%V" --saved-options' in command
    assert "private" not in command.lower()


def test_development_command_includes_main_script() -> None:
    command = pbo_context_menu.command_line(
        executable=Path(r"C:\Python313\python.exe"),
        main_script=Path(r"F:\RaiZo Tools\main.py"),
    )

    assert '"F:\\RaiZo Tools\\main.py"' in command


class FakeRegistry:
    HKEY_CURRENT_USER = object()
    KEY_READ = 1
    KEY_WRITE = 2
    REG_SZ = 1

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.deleted: list[str] = []

    def CreateKeyEx(self, _root, path: str, _reserved: int, _access: int):
        return _Key(path)

    def OpenKey(self, _root, path: str, _reserved: int, _access: int):
        if not any(key_path == path for key_path, _name in self.values):
            raise FileNotFoundError(path)
        return _Key(path)

    def SetValueEx(self, key, name: str, _reserved: int, _kind: int, value: str):
        self.values[(key.path, name)] = value

    def QueryValueEx(self, key, name: str):
        return self.values[(key.path, name)], self.REG_SZ

    def DeleteKey(self, _root, path: str):
        self.deleted.append(path)
        for item in [item for item in self.values if item[0] == path]:
            del self.values[item]


class _Key:
    def __init__(self, path: str) -> None:
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


def test_install_and_remove_context_menu_use_current_user_registry() -> None:
    registry = FakeRegistry()
    executable = Path(r"C:\RaiZoTools\RaiZoTools.exe")

    pbo_context_menu.install(executable=executable, registry=registry)

    assert registry.values[(pbo_context_menu.MENU_KEY, "")] == "Собрать PBO — RaiZo Tools"
    assert registry.values[(pbo_context_menu.MENU_KEY, "Icon")] == str(executable)
    assert "--saved-options" in registry.values[(pbo_context_menu.COMMAND_KEY, "")]
    assert pbo_context_menu.is_installed(registry=registry)

    pbo_context_menu.remove(registry=registry)

    assert registry.deleted == [pbo_context_menu.COMMAND_KEY, pbo_context_menu.MENU_KEY]
