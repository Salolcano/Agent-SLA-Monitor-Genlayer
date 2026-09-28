"""
Focused tests for contracts/sla_monitor.py using GenLayer's Direct Mode
testing framework (`pip install genlayer-test`, run with `pytest tests/ -v`
or `gltest`).

These run the contract's Python directly in-memory -- no Docker, no Studio,
no network -- with the LLM call inside request_judgment() replaced by
direct_vm.mock_llm() so verdicts are deterministic.

Covers exactly the three behaviors this revision was about:
  1. test_repeated_intervals_are_isolated
  2. test_request_judgment_before_closing_reporting_phase_reverts
  3. test_close_sla_with_pending_activity_reverts
plus one extra for the strict verdict-type validation added alongside them.
"""

import json

import pytest


SLA_TERMS = (
    "Respond to every support ticket within 1 hour. Reasonable effort is "
    "fine on complex requests, but the response must substantively address "
    "what was asked."
)

CLEAN_VERDICT = json.dumps({"breach": False, "reasoning": "Handled within SLA."})
BREACH_VERDICT = json.dumps({"breach": True, "reasoning": "No substantive response for 6 hours."})


def _deploy(direct_deploy, client_hex: str, slash_bps: int = 2000):
    return direct_deploy("contracts/sla_monitor.py", client_hex, SLA_TERMS, slash_bps)


def test_repeated_intervals_are_isolated(direct_vm, direct_deploy, direct_bob):
    """
    A judgment must only ever see the CURRENT interval's reports -- a
    shorter second interval must not inherit leftover entries from a
    longer first one, and the activity log must read empty again right
    after each verdict.
    """
    sla = _deploy(direct_deploy, direct_bob.as_hex)

    # Interval 1: three events, ends clean.
    sla.report_activity(args=["evt-1", "First response in 5 min, resolved.", "ticket://1"])
    sla.report_activity(args=["evt-2", "Second ticket, resolved within SLA.", "ticket://2"])
    sla.report_activity(args=["evt-3", "Third ticket, resolved within SLA.", "ticket://3"])
    assert len(sla.get_activity_log().call()) == 3

    sla.close_reporting_phase()

    direct_vm.mock_llm(r"SLA TERMS", CLEAN_VERDICT)
    sla.request_judgment()

    info = sla.get_sla_info().call()
    assert info["clean_count"] == 1
    assert info["breach_count"] == 0
    assert info["awaiting_judgment"] is False
    # Interval sealed -- nothing from interval 1 should still be "current".
    assert sla.get_activity_log().call() == {}

    # Interval 2: a single event, and it must NOT see evt-1/evt-2/evt-3.
    sla.report_activity(args=["evt-4", "Fourth ticket, response after 6 hours.", "ticket://4"])
    log = sla.get_activity_log().call()
    assert len(log) == 1
    assert "evt-4" in json.dumps(log)
    assert "evt-1" not in json.dumps(log)

    sla.close_reporting_phase()

    direct_vm.clear_mocks()
    direct_vm.mock_llm(r"SLA TERMS", BREACH_VERDICT)
    sla.request_judgment()

    info = sla.get_sla_info().call()
    assert info["breach_count"] == 1
    assert info["clean_count"] == 1  # unchanged from interval 1
    assert int(info["bond_remaining"]) <= int(info["bond_total"])
    assert sla.get_activity_log().call() == {}


def test_request_judgment_before_closing_reporting_phase_reverts(direct_vm, direct_deploy, direct_bob):
    """
    request_judgment() must fail while the reporting phase is still open,
    even though activity has been logged -- close_reporting_phase() is a
    required, separate step.
    """
    sla = _deploy(direct_deploy, direct_bob.as_hex)

    sla.report_activity(args=["evt-1", "Handled on time.", "ticket://1"])

    with direct_vm.expect_revert("reporting phase is not complete"):
        sla.request_judgment()

    # Closing the phase first makes the same call succeed.
    sla.close_reporting_phase()
    direct_vm.mock_llm(r"SLA TERMS", CLEAN_VERDICT)
    sla.request_judgment()
    assert sla.get_sla_info().call()["clean_count"] == 1


def test_close_sla_with_pending_activity_reverts(direct_vm, direct_deploy, direct_bob):
    """
    close_sla() must fail whenever there is unjudged activity outstanding,
    whether the reporting phase is still open (unclosed reports) or already
    closed and simply awaiting a verdict.
    """
    sla = _deploy(direct_deploy, direct_bob.as_hex)

    # Case A: reporting phase still open, one unclosed report pending.
    sla.report_activity(args=["evt-1", "Handled on time.", "ticket://1"])
    with direct_vm.expect_revert("cannot close the SLA while activity is pending judgment"):
        sla.close_sla()

    # Case B: reporting phase closed, awaiting judgment -- still blocked.
    sla.close_reporting_phase()
    with direct_vm.expect_revert("cannot close the SLA while activity is pending judgment"):
        sla.close_sla()

    # Once judged, nothing pending, closing succeeds.
    direct_vm.mock_llm(r"SLA TERMS", CLEAN_VERDICT)
    sla.request_judgment()
    sla.close_sla()
    assert sla.get_sla_info().call()["is_active"] is False


def test_verdict_must_be_a_strict_json_object_with_boolean_breach(direct_vm, direct_deploy, direct_bob):
    """
    A verdict that resembles the expected shape but has the wrong type for
    `breach` (e.g. a string instead of a real boolean) must be rejected
    rather than silently coerced -- bool("false") is True in Python, so a
    naive cast would flip a validator's "no breach" into a breach.
    """
    sla = _deploy(direct_deploy, direct_bob.as_hex)

    sla.report_activity(args=["evt-1", "Handled on time.", "ticket://1"])
    sla.close_reporting_phase()

    direct_vm.mock_llm(r"SLA TERMS", json.dumps({"breach": "false", "reasoning": "looks clean"}))
    with direct_vm.expect_revert("must be a boolean"):
        sla.request_judgment()
