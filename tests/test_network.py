from datetime import date
from types import SimpleNamespace
import pytest
from backend.models import NetworkRule
from backend.security import network_allowed,validate_cidr
def rule(cidr,proxy=False): return NetworkRule(policy_id=1,cidr=cidr,label="x",campus="x",is_trusted_proxy=proxy,active_from=date.today())
def test_ipv4_ipv6_and_fail_closed():
    rules=[rule("10.42.0.0/16"),rule("2001:db8:42::/48")]
    assert network_allowed("10.42.1.2",rules); assert network_allowed("2001:db8:42::2",rules)
    assert not network_allowed("8.8.8.8",rules); assert not network_allowed("10.42.1.2",[])
def test_allow_all_rejected():
    with pytest.raises(ValueError): validate_cidr("0.0.0.0/0")
    with pytest.raises(ValueError): validate_cidr("::/0")

