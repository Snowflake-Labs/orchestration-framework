from streamlit.testing.v1 import AppTest


def test_app():
    at = AppTest.from_file(
        "demo_app/demo_app.py",
        default_timeout=30,
    )
    at.run()
    assert not at.exception
