import pytest

from app.modules.exploration.u2_dump import U2Dumper, U2Unavailable, normalize_u2_xml
from app.modules.exploration.ui_dump import parse_ui_hierarchy

# uiautomator2 style: the class name is the tag.
U2_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <android.widget.FrameLayout index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.app"
      content-desc="" checkable="false" checked="false" clickable="false" enabled="true" focusable="false"
      focused="false" scrollable="false" long-clickable="false" password="false" selected="false" visible-to-user="true"
      bounds="[0,0][1080,2400]">
    <android.widget.Button index="0" text="English" resource-id="com.app:id/lang" class="android.widget.Button"
        package="com.app" content-desc="" checkable="false" checked="false" clickable="true" enabled="true"
        focusable="true" focused="false" scrollable="false" long-clickable="false" password="false" selected="false"
        visible-to-user="true" bounds="[80,740][1000,860]" />
  </android.widget.FrameLayout>
</hierarchy>"""


def test_u2_xml_is_normalised_for_the_existing_parser() -> None:
    elements = parse_ui_hierarchy(normalize_u2_xml(U2_XML))
    assert [e.class_name for e in elements] == ["android.widget.FrameLayout", "android.widget.Button"]
    button = elements[1]
    assert button.text == "English" and button.clickable and button.bounds == (80, 740, 1000, 860)


def test_dumper_returns_normalised_xml() -> None:
    class Device:
        def dump_hierarchy(self, **kwargs):
            return U2_XML

    xml = U2Dumper("emulator-5554", connect=lambda serial: Device()).dump_xml()
    assert "<node" in xml and "android.widget.Button" not in xml.split("<node")[0]


def test_disables_itself_after_repeated_failures() -> None:
    attempts = []

    def connect(serial):
        attempts.append(1)
        raise OSError("no device")

    dumper = U2Dumper("emulator-5554", connect=connect, max_failures=3)
    for _ in range(3):
        with pytest.raises(OSError):
            dumper.dump_xml()
    assert dumper.disabled
    with pytest.raises(U2Unavailable):
        dumper.dump_xml()
    assert len(attempts) == 3  # no further connection attempts once disabled


def test_success_resets_the_failure_count() -> None:
    state = {"fail": True}

    class Device:
        def dump_hierarchy(self, **kwargs):
            if state["fail"]:
                raise OSError("busy")
            return U2_XML

    dumper = U2Dumper("s", connect=lambda s: Device(), max_failures=3)
    with pytest.raises(OSError):
        dumper.dump_xml()
    state["fail"] = False
    dumper.dump_xml()
    assert not dumper.disabled and dumper._failures == 0
