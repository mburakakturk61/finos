from datetime import datetime, timezone
import uuid

import pytest

from app.integrations.analysis_http.contracts import AuthenticationStrength
from app.security.contracts import ProvisioningAuthority
from app.security.historical_binding import HistoricalTenantBindingCommand


def _authority(kind="PLATFORM"):
    return ProvisioningAuthority(
        "platform-e2", kind, None, None,
        AuthenticationStrength.PHISHING_RESISTANT,
    )


def test_historical_binding_command_is_immutable_and_exact():
    command = HistoricalTenantBindingCommand(
        _authority(), "historical-bind-0001", "tenant-one",
        (uuid.uuid4(),), (), (), datetime.now(timezone.utc), "corr-e2",
    )
    assert command.tenant_key == "tenant-one"
    with pytest.raises((AttributeError, TypeError)):
        command.tenant_key = "other"


@pytest.mark.parametrize("tenant_key", ("Tenant-One", " tenant-one", "tenant_öne"))
def test_historical_binding_rejects_noncanonical_tenant(tenant_key):
    with pytest.raises(ValueError):
        HistoricalTenantBindingCommand(
            _authority(), "historical-bind-0002", tenant_key,
            (), (), (), datetime.now(timezone.utc), "corr-e2",
        )


def test_historical_binding_rejects_non_platform_authority_and_duplicate_resources():
    resource_id = uuid.uuid4()
    with pytest.raises(ValueError):
        HistoricalTenantBindingCommand(
            _authority("TENANT_ADMIN"), "historical-bind-0003", "tenant-one",
            (resource_id,), (), (), datetime.now(timezone.utc), "corr-e2",
        )
    with pytest.raises(ValueError):
        HistoricalTenantBindingCommand(
            _authority(), "historical-bind-0004", "tenant-one",
            (resource_id, resource_id), (), (), datetime.now(timezone.utc), "corr-e2",
        )
