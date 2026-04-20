"""
Sanity test — guarantees pytest collection produces a non-empty result for T01.
This is the only test that ships in T01 for the backend unit suite.
"""


def test_truthy():
    """Trivially pass to confirm pytest collects and exits 0 for T01."""
    assert True
