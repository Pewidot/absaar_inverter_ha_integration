"""Enable the custom integration with network access blocked by the test plugin."""

import pytest


@pytest.fixture(autouse=True)
def custom_integrations_enabled(enable_custom_integrations):
    """Use the real Home Assistant loader with mocked device and cloud I/O."""
