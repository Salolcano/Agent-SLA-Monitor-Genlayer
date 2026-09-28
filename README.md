# Agent SLA Monitor

A continuous, on-chain judge for the commitments one agent makes to another --
response time, quality, resolution rate -- enforced by GenLayer validator
consensus instead of a support ticket.

Built for a GenLayer hackathon. Not an official GenLayer product.

## The idea

Agents already hire and coordinate with other agents. The promises they make
to each other ("respond within 5 minutes", "resolve 90% of tickets without
escalation") usually live in a prompt or a listing page, with nothing
watching whether they're actually kept -- and no way to judge a gray-area
breach, because that takes reasoning, not a threshold.

**Agent SLA Monitor** is a single Intelligent Contract that:

1. Records a plain-English SLA between a `provider` and a `client`, backed by
   a GEN bond.
2. Lets either party log **attributable, verifiable** events for the current
   interval (`report_activity`) -- each entry carries an external event id,
   a description, and an evidence reference, plus the reporter's address and
   role recorded automatically. Free-form, unlabeled text is not accepted.
3. Requires the reporting phase to be explicitly sealed (`close_reporting_phase`)
   before a verdict can be requested at all -- this is what makes an "early"
   judgment on a still-open interval impossible.
4. On `request_judgment`, asks GenLayer's validator set to read the SLA terms
   and *only the current interval's* sealed activity log, and reach a
   **breach / no-breach** verdict by consensus
   (`gl.eq_principle.prompt_comparative`) -- a judgment call a plain if/else
   check can't make. The verdict's shape is validated strictly: a `breach`
   field that isn't a real boolean, or a missing/empty `reasoning`, reverts
   the transaction instead of being silently coerced.
5. A confirmed breach slashes a configurable percentage of the remaining
   bond to the client and is recorded permanently. A clean interval builds
   the provider's track record (`clean_count` / `breach_count`). Either
   party can then close the SLA -- but only once nothing is left pending, so
   a party can't sidestep a verdict already in motion by closing early.

This is a real deployment target, not a simulation: every write goes through
GenLayer Studio Next's fee-charging consensus v0.6 lifecycle, and the
judgment step genuinely calls an LLM through GenVM and requires validators to
agree.

## Project layout

```
contracts/
  sla_monitor.py     # the Intelligent Contract (deploy this in Studio Next)
frontend/             # Next.js app that reads/writes the deployed contract
  app/
  lib/genlayer.ts     # all GenLayer read/write logic lives here
```

## The contract

`contracts/sla_monitor.py` is written in the same GenVM dialect as GenLayer
Studio's bundled sample contracts (`gl.contract.Contract`, `gl.public.view` /
`gl.public.write` / `gl.public.write.payable`, `gl.eq_principle`,
`gl.storage.TreeMap`, `gl.vm.UserError`).

Public methods:

| Method | Who | What it does |
| --- | --- | --- |
| `deposit_bond()` (payable) | provider | Stakes GEN behind the SLA. |
| `report_activity(event_id, description, evidence_ref)` | provider or client | Appends one attributable event to the current interval's log. Rejects duplicate `event_id`s within the same interval, and is blocked once the reporting phase is closed. |
| `close_reporting_phase()` | provider or client | Seals the current interval (requires at least one report). Required before `request_judgment()` will run -- this is the gate against early judgment. |
| `request_judgment()` | anyone | Sends the SLA terms + the sealed interval's activity log to the validator set; strictly validates the verdict's shape; records a breach/no-breach verdict; slashes the bond on a confirmed breach; opens a fresh interval. |
| `close_sla()` | provider or client | Deactivates the SLA. Reverts if any activity is still pending judgment (phase open with reports, or phase closed and awaiting a verdict). |
| `withdraw_remaining_bond()` | provider | Withdraws whatever bond is left, once closed. |
| `get_sla_info()`, `get_activity_log()`, `get_verdicts()` | anyone (view) | Read current state. `get_activity_log()` only ever returns the current, not-yet-judged interval. |

### Lifecycle per interval

```
report_activity()  (repeatable, attributable events only)
        v
close_reporting_phase()   <- required; blocks report_activity() and request_judgment() from
        v                     racing each other, and is the "early judgment" guard
request_judgment()  (validator consensus; breach/no-breach + reasoning)
        v
   back to report_activity() for the next interval
```

`close_sla()` only succeeds between intervals, once a judgment has resolved
everything pending -- never mid-phase.

### Deploying the contract on Studio Next

1. Open the Studio Next web app and connect/create an account there (it has
   a built-in faucet -- use it to fund that account with test GEN).
2. Create a new contract, paste in the full contents of
   `contracts/sla_monitor.py`, and deploy it.
3. When prompted for constructor arguments, provide:
   - `client` -- the wallet address of the party being served (a second
     Studio account, or any address you control)
   - `sla_terms` -- the plain-English commitment, e.g. `"Respond to every
     ticket within 1 hour. Reasonable effort is enough on complex requests;
     the request must still be substantively addressed."`
   - `slash_bps` -- how much of the remaining bond a confirmed breach
     slashes, in basis points (e.g. `2000` = 20%)
4. Copy the deployed contract address -- the frontend needs it as
   `NEXT_PUBLIC_CONTRACT_ADDRESS`.

Network details this project targets:

- RPC: `https://studio-next.genlayer.com/api`
- Chain ID: `61997`
- Explorer: `https://explorer-studio-dev.genlayer.com/`

## The frontend

`frontend/` is a plain Next.js 15 + TypeScript app. It talks to the contract
directly with `genlayer-js@2.0.0-rc.1` -- no wallet-abstraction libraries, so
there's as little as possible standing between your click and the chain.

Every write (`deposit_bond`, `report_activity`, `request_judgment`,
`close_sla`, `withdraw_remaining_bond`) follows the same flow required by
consensus v0.6: estimate the fee policy for that exact call
(`estimateTransactionFeesForWrite`), submit the transaction with that
`distribution` + `feeValue`, then wait for finalization and check
`isSuccessful()` before treating anything as done. See `lib/genlayer.ts` for
the whole flow in one place.

Required environment variable:

```
NEXT_PUBLIC_CONTRACT_ADDRESS=0x... # the address from the deploy step above
```

### Using the app

1. Click **Connect wallet** (MetaMask or any EIP-1193 wallet). The app will
   prompt your wallet to add/switch to the Studio Next network automatically.
2. Make sure your connected wallet is funded with test GEN on Studio Next
   (use the same account you deployed with for the provider role, or the
   `client` address you set at deploy time for the client role).
3. As the provider: deposit a bond.
4. As either party: log a few activity entries for the interval.
5. Anyone: request a validator judgment and watch the verdict come back.
6. Repeat step 4-5 for as many intervals as you like; close the SLA and
   withdraw the remaining bond when you're done.

## Tests

`tests/test_sla_monitor.py` uses GenLayer's Direct Mode testing framework
(`pip install genlayer-test`), which runs the contract's Python directly
in-memory -- no Docker or Studio needed -- with the LLM call mocked so
verdicts are deterministic. Run with:

```
pip install genlayer-test
pytest tests/ -v
```

It covers:

- **Repeated intervals are isolated** -- a shorter second interval never
  inherits leftover entries from a longer first one, and the activity log
  reads empty again right after each verdict.
- **Early judgment reverts** -- `request_judgment()` fails while the
  reporting phase is still open, even with activity already logged.
- **Closing with pending activity reverts** -- `close_sla()` fails both
  while reports are sitting in an unclosed phase and while a closed phase
  is awaiting a verdict.
- **Strict verdict validation** -- a verdict where `breach` isn't a real
  boolean is rejected rather than coerced.

## What's next (post-hackathon)

- A lightweight reporting hook that calls `report_activity` automatically
  from an agent's own logs, instead of manual entry.
- A portable reputation score other GenLayer products could query.
- An appeal path for a contested verdict, escalating to a larger validator
  jury.
