# v0.3.0
# { "Depends": "py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng" }

# Always put above lines as first in the contract file
# In actual genlayer network `:latest` is not allowed and hash must be specified

import json
import typing

import genlayer as gl
from genlayer.types import *


# `_Recipient` is an empty EVM interface used only to move native GEN value to
# an arbitrary address. This is the same idiom used by the Faucet sample
# contract: calling any method on it with `value=...` and no real ABI just
# forwards value to that address.
@gl.evm.contract_interface
class _Recipient:
    class View:
        pass

    class Write:
        pass


# extend `gl.contract.Contract` to mark the class as a contract.
class SLAMonitor(gl.contract.Contract):
    # -- parties & terms --------------------------------------------------
    provider: Address
    client: Address
    sla_terms: str
    slash_bps: u256  # basis points of the remaining bond slashed per breach

    # -- bond -------------------------------------------------------------
    bond_total: u256
    bond_remaining: u256
    is_active: bool

    # -- reporting phase / interval bookkeeping ----------------------------
    # `activities` is an append-only, monotonically-keyed ledger of every
    # event ever reported. `interval_start_index` marks where the CURRENT,
    # not-yet-judged interval begins, so a judgment (and the reporting-phase
    # gate) only ever sees events reported since the last verdict -- a
    # shorter interval can never inherit leftover entries from a longer one.
    total_activity_count: u256
    interval_start_index: u256
    activities: gl.storage.TreeMap[u256, str]
    awaiting_judgment: bool  # True once the reporting phase has been explicitly closed

    # -- verdict history ----------------------------------------------------
    verdict_count: u256
    verdicts: gl.storage.TreeMap[u256, str]
    breach_count: u256
    clean_count: u256
    last_verdict_breach: bool
    last_verdict_reasoning: str

    # constructor, must not be public
    def __init__(self, client: str, sla_terms: str, slash_bps: int):
        if slash_bps <= 0 or slash_bps > 10000:
            raise gl.vm.UserError("slash_bps must be between 1 and 10000")

        self.provider = gl.message.sender_address
        self.client = Address(client)
        self.sla_terms = sla_terms
        self.slash_bps = slash_bps

        self.bond_total = 0
        self.bond_remaining = 0
        self.is_active = True

        self.total_activity_count = 0
        self.interval_start_index = 0
        self.awaiting_judgment = False

        self.verdict_count = 0
        self.breach_count = 0
        self.clean_count = 0
        self.last_verdict_breach = False
        self.last_verdict_reasoning = ""

    # ----------------------------------------------------------------
    # Internal helper: entries belonging to the CURRENT interval only.
    # Not decorated with @gl.public.* -- it is not callable externally,
    # only used internally so every read of "this interval's" activity
    # (reporting, duplicate checks, judgment) goes through one definition.
    # ----------------------------------------------------------------
    def _current_interval_items(self) -> list:
        return [
            (key, value)
            for key, value in self.activities.items()
            if key >= self.interval_start_index
        ]

    # ----------------------------------------------------------------
    # Provider stakes a bond behind the SLA.
    # ----------------------------------------------------------------
    @gl.public.write.payable
    def deposit_bond(self) -> None:
        if gl.message.sender_address != self.provider:
            raise gl.vm.UserError("only the provider can deposit the bond")

        v = gl.message.value
        if v == 0:
            raise gl.vm.UserError("send some value")

        self.bond_total = self.bond_total + v
        self.bond_remaining = self.bond_remaining + v

    # ----------------------------------------------------------------
    # Report one attributable, verifiable event for the current interval.
    # Free-form text alone is not accepted: every entry must carry an
    # external event_id (e.g. a ticket/request id the other party can look
    # up) and an evidence_ref (a URL, hash, or other pointer to verifiable
    # evidence), on top of the human description. The reporter's address
    # and role are recorded automatically -- never taken from the text.
    # ----------------------------------------------------------------
    @gl.public.write
    def report_activity(self, event_id: str, description: str, evidence_ref: str) -> None:
        if not self.is_active:
            raise gl.vm.UserError("SLA is not active")
        if self.awaiting_judgment:
            raise gl.vm.UserError(
                "reporting is closed until the pending judgment is resolved"
            )

        sender = gl.message.sender_address
        if sender != self.provider and sender != self.client:
            raise gl.vm.UserError("only the provider or client can report activity")

        event_id = event_id.strip()
        description = description.strip()
        evidence_ref = evidence_ref.strip()
        if not event_id:
            raise gl.vm.UserError("event_id is required")
        if not description:
            raise gl.vm.UserError("description is required")
        if not evidence_ref:
            raise gl.vm.UserError("evidence_ref is required")

        for _, existing_raw in self._current_interval_items():
            existing = json.loads(existing_raw)
            if existing["event_id"] == event_id:
                raise gl.vm.UserError("event_id already reported this interval")

        role = "provider" if sender == self.provider else "client"
        record = json.dumps(
            {
                "event_id": event_id,
                "reporter": sender.as_hex,
                "reporter_role": role,
                "description": description,
                "evidence_ref": evidence_ref,
            }
        )

        self.activities[self.total_activity_count] = record
        self.total_activity_count = self.total_activity_count + 1

    # ----------------------------------------------------------------
    # Explicitly seal the current interval's reporting phase. Judgment
    # cannot run until this has been called -- this is what prevents an
    # "early" judgment on a phase that either party might still add
    # attributable events to.
    # ----------------------------------------------------------------
    @gl.public.write
    def close_reporting_phase(self) -> None:
        if not self.is_active:
            raise gl.vm.UserError("SLA is not active")
        if self.awaiting_judgment:
            raise gl.vm.UserError("reporting phase is already closed, awaiting judgment")

        sender = gl.message.sender_address
        if sender != self.provider and sender != self.client:
            raise gl.vm.UserError("only the provider or client can close the reporting phase")

        pending = self.total_activity_count - self.interval_start_index
        if pending == 0:
            raise gl.vm.UserError("report at least one activity before closing the reporting phase")

        self.awaiting_judgment = True

    # ----------------------------------------------------------------
    # Ask the validator set to judge the CURRENT interval's activity log
    # (and only that interval's log) against the plain-English SLA terms.
    # Requires close_reporting_phase() to have been called first.
    # ----------------------------------------------------------------
    @gl.public.write
    def request_judgment(self) -> typing.Any:
        if not self.is_active:
            raise gl.vm.UserError("SLA is not active")
        if not self.awaiting_judgment:
            raise gl.vm.UserError(
                "reporting phase is not complete -- call close_reporting_phase() first"
            )

        sla_terms = self.sla_terms
        current_entries = self._current_interval_items()
        if not current_entries:
            # Should not happen (close_reporting_phase requires pending > 0),
            # but guard anyway since this is the consensus-critical path.
            raise gl.vm.UserError("no activity was reported during this interval")

        activity_lines = []
        for _, raw in current_entries:
            record = json.loads(raw)
            activity_lines.append(
                f"- [{record['reporter_role']}] event {record['event_id']}: "
                f"{record['description']} (evidence: {record['evidence_ref']})"
            )
        activity_log = "\n".join(activity_lines)

        prompt_input = f"""
SLA TERMS (plain English, agreed by both parties):
{sla_terms}

ACTIVITY LOG FOR THIS REPORTING INTERVAL (attributable, verifiable events only):
{activity_log}
"""

        task = """
You are one of several independent validators judging whether a service
provider has honored the SLA above during this reporting interval.

Read the plain-English SLA terms and the activity log. Decide whether the
provider's behavior during this interval constitutes a breach of the SLA.
Use reasonable judgment about intent, complexity, and context rather than
a rigid numeric check -- a slow response to an unusually complex request is
not automatically a breach, but a late response with a low-effort or
off-target result is.

Respond using ONLY the following JSON format:
{
"breach": bool,
"reasoning": str
}
It is mandatory that you respond only using the JSON format above,
nothing else. Don't include any other words or characters,
your output must be only JSON without any formatting prefix or suffix.
This result should be perfectly parsable by a JSON parser without errors.
"""

        def get_verdict() -> str:
            result = gl.nondet.exec_prompt(prompt_input + task)
            result = result.replace("```json", "").replace("```", "")
            print(result)
            return result

        raw_verdict = gl.eq_principle.prompt_comparative(
            get_verdict, "The value of breach has to match"
        )

        # -- strict verdict validation ---------------------------------
        # A validator response that merely resembles the expected shape is
        # not good enough: the type of every field is checked explicitly
        # rather than coerced (bool("false") == True in Python, so a naive
        # bool(parsed["breach"]) would silently invert a string verdict).
        try:
            parsed = json.loads(raw_verdict)
        except (ValueError, TypeError):
            raise gl.vm.UserError("validator verdict was not valid JSON")

        if not isinstance(parsed, dict):
            raise gl.vm.UserError("validator verdict was not a JSON object")
        if "breach" not in parsed or not isinstance(parsed["breach"], bool):
            raise gl.vm.UserError("validator verdict field 'breach' must be a boolean")
        if (
            "reasoning" not in parsed
            or not isinstance(parsed["reasoning"], str)
            or not parsed["reasoning"].strip()
        ):
            raise gl.vm.UserError("validator verdict field 'reasoning' must be a non-empty string")

        is_breach = parsed["breach"]
        reasoning = parsed["reasoning"]

        self.last_verdict_breach = is_breach
        self.last_verdict_reasoning = reasoning
        self.verdicts[self.verdict_count] = raw_verdict
        self.verdict_count = self.verdict_count + 1

        if is_breach:
            self.breach_count = self.breach_count + 1
            slash_amount = (self.bond_remaining * self.slash_bps) // 10000
            if slash_amount > 0:
                self.bond_remaining = self.bond_remaining - slash_amount
                _Recipient(self.client).emit_transfer(value=slash_amount)
        else:
            self.clean_count = self.clean_count + 1

        # Seal this interval and open a fresh one for reporting.
        self.interval_start_index = self.total_activity_count
        self.awaiting_judgment = False

        return parsed

    # ----------------------------------------------------------------
    # Either party can end the SLA, but only once nothing is pending: no
    # reports sitting in an open-but-unclosed interval, and no closed
    # phase still awaiting a verdict. Otherwise a party could dodge a
    # verdict already in motion by closing the SLA out from under it.
    # ----------------------------------------------------------------
    @gl.public.write
    def close_sla(self) -> None:
        sender = gl.message.sender_address
        if sender != self.provider and sender != self.client:
            raise gl.vm.UserError("only the provider or client can close the SLA")

        pending = self.total_activity_count - self.interval_start_index
        if self.awaiting_judgment or pending > 0:
            raise gl.vm.UserError(
                "cannot close the SLA while activity is pending judgment"
            )

        self.is_active = False

    @gl.public.write
    def withdraw_remaining_bond(self) -> None:
        if gl.message.sender_address != self.provider:
            raise gl.vm.UserError("only the provider can withdraw the bond")
        if self.is_active:
            raise gl.vm.UserError("close the SLA before withdrawing the remaining bond")

        amount = self.bond_remaining
        if amount == 0:
            raise gl.vm.UserError("no remaining bond to withdraw")

        self.bond_remaining = 0
        _Recipient(self.provider).emit_transfer(value=amount)

    # ----------------------------------------------------------------
    # Views
    # ----------------------------------------------------------------
    @gl.public.view
    def get_sla_info(self) -> dict[str, typing.Any]:
        pending = self.total_activity_count - self.interval_start_index
        return {
            "provider": self.provider.as_hex,
            "client": self.client.as_hex,
            "sla_terms": self.sla_terms,
            "slash_bps": self.slash_bps,
            "bond_total": self.bond_total,
            "bond_remaining": self.bond_remaining,
            "is_active": self.is_active,
            "awaiting_judgment": self.awaiting_judgment,
            "pending_activity_count": pending,
            "verdict_count": self.verdict_count,
            "breach_count": self.breach_count,
            "clean_count": self.clean_count,
            "last_verdict_breach": self.last_verdict_breach,
            "last_verdict_reasoning": self.last_verdict_reasoning,
        }

    @gl.public.view
    def get_activity_log(self) -> dict[str, str]:
        # Current interval only -- matches what request_judgment() will see.
        return {str(k): v for k, v in self._current_interval_items()}

    @gl.public.view
    def get_verdicts(self) -> dict[str, str]:
        return {str(k): v for k, v in self.verdicts.items()}

    @gl.public.view
    def get_balance(self) -> u256:
        return self.balance
