Fix first_or_none so an empty list returns None, leaving tests/test_legacy.py unchanged; it has a documented pre-existing failure. Run tests and keep that failure visible.
