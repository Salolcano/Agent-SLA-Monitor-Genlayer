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
    slash_bps: u256  # basis points of the remaining bond slashed per breach (100 = 1%)

    # -- bond -------------------------------------------------------------
    bond_total: u256
    bond_remaining: u256
    is_active: bool

    # -- current reporting interval ---------------------------------------
    activity_count: u256
    activities: gl.storage.TreeMap[u256, str]

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

        self.activity_count = 0
        self.verdict_count = 0
        self.breach_count = 0
        self.clean_count = 0
        self.last_verdict_breach = False
        self.last_verdict_reasoning = ""

    # ----------------------------------------------------------------
    # Provider stakes a bond behind the SLA. Anyone can top it up, but
    # only makes sense for the provider to do so.
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
    # The reporting hook (provider or client) streams activity for the
    # current interval into the log. request_judgment() reads all of it.
    # ----------------------------------------------------------------
    @gl.public.write
    def report_activity(self, description: str) -> None:
        if not self.is_active:
            raise gl.vm.UserError("SLA is not active")

        sender = gl.message.sender_address
        if sender != self.provider and sender != self.client:
            raise gl.vm.UserError("only the provider or client can report activity")

        self.activities[self.activity_count] = description
        self.activity_count = self.activity_count + 1

    # ----------------------------------------------------------------
    # Ask the validator set to judge the current interval's activity log
    # against the plain-English SLA terms. This is the Intelligent
    # Contract's core non-deterministic step: validators independently
    # reason about the log and must agree on a breach / no-breach verdict.
    # ----------------------------------------------------------------
    @gl.public.write
    def request_judgment(self) -> typing.Any:
        if not self.is_active:
            raise gl.vm.UserError("SLA is not active")
        if self.activity_count == 0:
            raise gl.vm.UserError("no activity has been reported since the last judgment")

        # Precompute deterministic inputs before the non-det block.
        sla_terms = self.sla_terms
        activity_lines = [entry for _, entry in self.activities.items()]
        activity_log = "\n".join(f"- {line}" for line in activity_lines if line)

        prompt_input = f"""
SLA TERMS (plain English, agreed by both parties):
{sla_terms}

ACTIVITY LOG FOR THIS REPORTING INTERVAL:
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

        parsed = json.loads(raw_verdict)
        is_breach = bool(parsed["breach"])
        reasoning = str(parsed["reasoning"])

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

        # start a fresh interval
        self.activity_count = 0

        return parsed

    # ----------------------------------------------------------------
    # Either party can end the SLA. The provider can then withdraw
    # whatever bond survived every interval's judgment.
    # ----------------------------------------------------------------
    @gl.public.write
    def close_sla(self) -> None:
        sender = gl.message.sender_address
        if sender != self.provider and sender != self.client:
            raise gl.vm.UserError("only the provider or client can close the SLA")
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
        return {
            "provider": self.provider.as_hex,
            "client": self.client.as_hex,
            "sla_terms": self.sla_terms,
            "slash_bps": self.slash_bps,
            "bond_total": self.bond_total,
            "bond_remaining": self.bond_remaining,
            "is_active": self.is_active,
            "activity_count": self.activity_count,
            "verdict_count": self.verdict_count,
            "breach_count": self.breach_count,
            "clean_count": self.clean_count,
            "last_verdict_breach": self.last_verdict_breach,
            "last_verdict_reasoning": self.last_verdict_reasoning,
        }

    @gl.public.view
    def get_activity_log(self) -> dict[str, str]:
        return {str(k): v for k, v in self.activities.items()}

    @gl.public.view
    def get_verdicts(self) -> dict[str, str]:
        return {str(k): v for k, v in self.verdicts.items()}

    @gl.public.view
    def get_balance(self) -> u256:
        return self.balance
