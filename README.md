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
2. Lets either party stream activity for the current interval into an
   on-chain log (`report_activity`).
3. On `request_judgment`, asks GenLayer's validator set to read the SLA terms
   and the interval's activity log and reach a **breach / no-breach**
   verdict by consensus (`gl.eq_principle.prompt_comparative`) -- a judgment
   call a plain if/else check can't make.
4. A confirmed breach slashes a configurable percentage of the remaining
   bond to the client and is recorded permanently. A clean interval builds
   the provider's track record (`clean_count` / `breach_count`).

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
| `report_activity(description)` | provider or client | Appends one entry to the current interval's log. |
| `request_judgment()` | anyone | Sends the SLA terms + activity log to the validator set; records a breach/no-breach verdict; slashes the bond on a confirmed breach; resets the interval. |
| `close_sla()` | provider or client | Deactivates the SLA. |
| `withdraw_remaining_bond()` | provider | Withdraws whatever bond is left, once closed. |
| `get_sla_info()`, `get_activity_log()`, `get_verdicts()` | anyone (view) | Read current state. |

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

## What's next (post-hackathon)

- A lightweight reporting hook that calls `report_activity` automatically
  from an agent's own logs, instead of manual entry.
- A portable reputation score other GenLayer products could query.
- An appeal path for a contested verdict, escalating to a larger validator
  jury.
