from __future__ import annotations

import unittest

from parsers_pkg.source_executor import _coerce_raw_list, _coerce_raw_records, _safe_event_dicts


class TestSourceExecutorRobustness(unittest.TestCase):
    def test_safe_event_dicts_ignores_non_dict_events(self):
        events = _safe_event_dicts({"events": [None, "bad", {"severity": "warning"}]})
        self.assertEqual(events, [{"severity": "warning"}])

    def test_coerce_raw_list_wraps_single_payloads(self):
        self.assertEqual(_coerce_raw_list(None), [])
        self.assertEqual(_coerce_raw_list({"one": 1}), [{"one": 1}])
        self.assertEqual(_coerce_raw_list((1, 2)), [1, 2])

    def test_coerce_raw_records_filters_parser_unsafe_values(self):
        self.assertEqual(_coerce_raw_records({"one": 1}), [{"one": 1}])
        self.assertEqual(_coerce_raw_records(({"ok": True}, "bad", None)), [{"ok": True}])
        self.assertEqual(_coerce_raw_records("not a row"), [])


if __name__ == "__main__":
    unittest.main()
