from __future__ import annotations

from xml.etree.ElementTree import Element

from app.core.xmlutil import android_attr, children_by_tag


def extract_intent_filters(parent: Element) -> list[dict]:
    filters: list[dict] = []
    for intent in children_by_tag(parent, "intent-filter"):
        actions = [android_attr(el, "name") for el in children_by_tag(intent, "action")]
        categories = [android_attr(el, "name") for el in children_by_tag(intent, "category")]
        data_entries = []
        for data_el in children_by_tag(intent, "data"):
            entry = {
                "scheme": android_attr(data_el, "scheme"),
                "host": android_attr(data_el, "host"),
                "port": android_attr(data_el, "port"),
                "path": android_attr(data_el, "path"),
                "path_prefix": android_attr(data_el, "pathPrefix"),
                "path_pattern": android_attr(data_el, "pathPattern"),
                "mime_type": android_attr(data_el, "mimeType"),
            }
            if any(value is not None for value in entry.values()):
                data_entries.append(entry)
        filters.append(
            {
                "actions": [name for name in actions if name],
                "categories": [name for name in categories if name],
                "data": data_entries,
            }
        )
    return filters
