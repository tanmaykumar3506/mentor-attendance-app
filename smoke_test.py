"""Headless smoke test: opens every page and fails on any exception."""
from streamlit.testing.v1 import AppTest

at = AppTest.from_file("app.py", default_timeout=90)
at.run()
assert not at.exception, at.exception
pages = list(at.radio(key="nav").options)
for p in pages:
    at.radio(key="nav").set_value(p).run()
    assert not at.exception, (p, at.exception)
    print("OK", p, "| tables:", len(at.dataframe), "| metrics:", len(at.metric))
print("All pages rendered without errors.")
