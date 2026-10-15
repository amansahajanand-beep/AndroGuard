from app.core.config import settings
from app.modules.exploration.ui_controller import UIController

ADB_XML = '<hierarchy><node text="From adb" class="android.widget.TextView" package="p" bounds="[0,0][10,10]" clickable="true" enabled="true"/></hierarchy>'
U2_XML = '<hierarchy><node text="From u2" class="android.widget.TextView" package="p" bounds="[0,0][10,10]" clickable="true" enabled="true"/></hierarchy>'


class FakeResult:
    def __init__(self, stdout="", ok=True):
        self.stdout, self.stderr, self.ok, self.command = stdout, "", ok, "x"

    def fail_message(self, msg):
        return msg


class FakeAdb:
    serial = "emulator-5554"
    binary = "adb"

    def __init__(self, fail_dumps=0):
        self.fail_dumps = fail_dumps
        self.dump_calls = 0

    def shell(self, command, **kw):
        if command.startswith("uiautomator dump"):
            self.dump_calls += 1
            if self.dump_calls <= self.fail_dumps:
                return FakeResult("ERROR: could not get idle state.", ok=False)
            return FakeResult("UI hierchary dumped to: /sdcard/ui.xml")
        return FakeResult("")

    def run(self, args, **kw):
        return FakeResult(ADB_XML)


class StubU2:
    def __init__(self, xml=None, error=None):
        self.xml, self.error = xml, error

    def dump_xml(self):
        if self.error:
            raise self.error
        return self.xml


def controller(adb, u2, monkeypatch, enabled=True):
    monkeypatch.setattr(settings, "uiautomator2_enabled", enabled)
    ctl = UIController(adb)
    ctl._u2 = u2
    return ctl


def test_prefers_uiautomator2_and_skips_adb_dump(monkeypatch) -> None:
    adb = FakeAdb()
    dump = controller(adb, StubU2(xml=U2_XML), monkeypatch).dump_ui()
    assert dump.elements[0].text == "From u2" and adb.dump_calls == 0 and dump.path == "uiautomator2"


def test_falls_back_to_adb_when_uiautomator2_fails(monkeypatch) -> None:
    adb = FakeAdb()
    dump = controller(adb, StubU2(error=OSError("x")), monkeypatch).dump_ui()
    assert dump.elements[0].text == "From adb" and adb.dump_calls == 1


def test_adb_dump_is_retried_after_idle_state_errors(monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda s: None)
    adb = FakeAdb(fail_dumps=2)
    dump = controller(adb, StubU2(error=OSError("x")), monkeypatch).dump_ui()
    assert dump.elements[0].text == "From adb" and adb.dump_calls == 3


def test_disabled_setting_uses_adb_only(monkeypatch) -> None:
    adb = FakeAdb()
    dump = controller(adb, StubU2(xml=U2_XML), monkeypatch, enabled=False).dump_ui()
    assert dump.elements[0].text == "From adb"
