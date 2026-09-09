from __future__ import annotations

import logging

from app.core.xmlutil import android_attr, children_by_tag, find_application, typed_value
from app.modules.apk_analyzer.context import ApkContext

logger = logging.getLogger(__name__)


def extract_metadata(ctx: ApkContext) -> list[dict]:
    app = find_application(ctx.manifest_xml)
    if app is None:
        return []

    items: list[dict] = []
    for el in children_by_tag(app, "meta-data"):
        name = android_attr(el, "name")
        if not name:
            continue
        raw_value = android_attr(el, "value")
        resource = android_attr(el, "resource")
        if resource and (raw_value is None or raw_value == ""):
            value, value_type = resource, "resource"
        else:
            value, value_type = typed_value(raw_value)
            if resource and value_type == "null":
                value, value_type = resource, "resource"
        logger.debug("Extracted metadata key %s type=%s", name, value_type)
        items.append({"name": name, "value": value, "value_type": value_type})
    return items
