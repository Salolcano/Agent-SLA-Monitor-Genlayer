import { createClient, isSuccessful } from "genlayer-js";
import { studioDevnet } from "genlayer-js/chains";

// ---------------------------------------------------------------------------
// Network config -- GenLayer Studio Next (release-candidate stack).
// This is the environment the hackathon requires: fee-charging consensus
// v0.6, chain id 61997. "studio-next.genlayer.com" is a browser alias for
// the same canonical RPC at studio-dev.genlayer.com.
// ---------------------------------------------------------------------------
export const STUDIO_NEXT_CHAIN_ID_HEX = "0xf22d"; // 61997
export const STUDIO_NEXT_EXPLORER = "https://explorer-studio-dev.genlayer.com/";

export const STUDIO_NEXT_WALLET_PARAMS = {
  chainId: STUDIO_NEXT_CHAIN_ID_HEX,
  chainName: "GenLayer Studio Next",
  nativeCurrency: { name: "GEN", symbol: "GEN", decimals: 18 },
  rpcUrls: ["https://studio-next.genlayer.com/api"],
  blockExplorerUrls: [STUDIO_NEXT_EXPLORER],
};

export const CONTRACT_ADDRESS = (process.env.NEXT_PUBLIC_CONTRACT_ADDRESS ||
  "") as `0x${string}`;

// ---------------------------------------------------------------------------
// Wallet helpers
// ---------------------------------------------------------------------------
export function getEthereum(): any {
  if (typeof window === "undefined") return null;
  return (window as any).ethereum ?? null;
}

export async function connectWallet(): Promise<`0x${string}`> {
  const ethereum = getEthereum();
  if (!ethereum) {
    throw new Error(
      "No wallet found. Install MetaMask (or another EIP-1193 wallet) and reload the page."
    );
  }
  const accounts: string[] = await ethereum.request({
    method: "eth_requestAccounts",
  });
  await ensureStudioNextNetwork(ethereum);
  return accounts[0] as `0x${string}`;
}

export async function ensureStudioNextNetwork(ethereum: any): Promise<void> {
  try {
    await ethereum.request({
      method: "wallet_switchEthereumChain",
      params: [{ chainId: STUDIO_NEXT_CHAIN_ID_HEX }],
    });
  } catch (switchError: any) {
    // 4902 = chain not added to this wallet yet
    if (switchError?.code === 4902) {
      await ethereum.request({
        method: "wallet_addEthereumChain",
        params: [STUDIO_NEXT_WALLET_PARAMS],
      });
    } else {
      throw switchError;
    }
  }
}

// ---------------------------------------------------------------------------
// GenLayer clients
// ---------------------------------------------------------------------------
export function getReadClient() {
  return createClient({ chain: studioDevnet });
}

export function getWriteClient(account: `0x${string}`) {
  const ethereum = getEthereum();
  return createClient({ chain: studioDevnet, account, provider: ethereum });
}

// ---------------------------------------------------------------------------
// Reads (no wallet / fees needed)
// ---------------------------------------------------------------------------
export async function readSlaInfo(): Promise<Record<string, any>> {
  const client = getReadClient();
  return client.readContract({
    address: CONTRACT_ADDRESS,
    functionName: "get_sla_info",
    args: [],
  }) as Promise<Record<string, any>>;
}

export async function readActivityLog(): Promise<Record<string, string>> {
  const client = getReadClient();
  return client.readContract({
    address: CONTRACT_ADDRESS,
    functionName: "get_activity_log",
    args: [],
  }) as Promise<Record<string, string>>;
}

export async function readVerdicts(): Promise<Record<string, string>> {
  const client = getReadClient();
  return client.readContract({
    address: CONTRACT_ADDRESS,
    functionName: "get_verdicts",
    args: [],
  }) as Promise<Record<string, string>>;
}

// ---------------------------------------------------------------------------
// Writes -- every write on Studio Next / consensus v0.6 must carry a fee
// estimate + FeesDistribution. We estimate right before submitting rather
// than relying on a checked-in fee profile, which keeps this demo simple.
// ---------------------------------------------------------------------------
type WriteArgs = {
  account: `0x${string}`;
  functionName: string;
  args?: any[];
  value?: bigint;
};

export async function submitWrite({
  account,
  functionName,
  args = [],
  value,
}: WriteArgs) {
  const client = getWriteClient(account);
  const call: any = { address: CONTRACT_ADDRESS, functionName, args };
  if (value !== undefined) call.value = value;

  const estimate = await client.estimateTransactionFeesForWrite(call);

  const txId = await client.writeContract({
    ...call,
    fees: {
      distribution: estimate.distribution,
      feeValue: estimate.feeValue,
    },
  });

  const transaction: any = await client.waitForFinalization({ hash: txId });

  if (!isSuccessful(transaction)) {
    throw new Error(
      `Transaction did not succeed: ${transaction.statusName} / ${transaction.txExecutionResultName}`
    );
  }

  return { txId, transaction };
}

export const writeDepositBond = (account: `0x${string}`, valueWei: bigint) =>
  submitWrite({ account, functionName: "deposit_bond", args: [], value: valueWei });

export const writeReportActivity = (account: `0x${string}`, description: string) =>
  submitWrite({ account, functionName: "report_activity", args: [description] });

export const writeRequestJudgment = (account: `0x${string}`) =>
  submitWrite({ account, functionName: "request_judgment", args: [] });

export const writeCloseSla = (account: `0x${string}`) =>
  submitWrite({ account, functionName: "close_sla", args: [] });

export const writeWithdrawBond = (account: `0x${string}`) =>
  submitWrite({ account, functionName: "withdraw_remaining_bond", args: [] });

// ---------------------------------------------------------------------------
// GEN <-> wei helpers (avoid floating point on 18-decimal amounts)
// ---------------------------------------------------------------------------
export function parseGen(amount: string): bigint {
  const trimmed = amount.trim();
  if (!trimmed) return 0n;
  const [whole, frac = ""] = trimmed.split(".");
  const fracPadded = (frac + "0".repeat(18)).slice(0, 18);
  const wholeBig = BigInt(whole === "" ? "0" : whole);
  const fracBig = BigInt(fracPadded === "" ? "0" : fracPadded);
  return wholeBig * 10n ** 18n + fracBig;
}

export function formatGen(value: bigint | number | string | undefined): string {
  if (value === undefined) return "0";
  const v = BigInt(value);
  const whole = v / 10n ** 18n;
  const frac = v % 10n ** 18n;
  const fracStr = frac.toString().padStart(18, "0").replace(/0+$/, "");
  return fracStr ? `${whole}.${fracStr}` : `${whole}`;
}

export function shortAddress(addr?: string): string {
  if (!addr) return "--";
  return `${addr.slice(0, 6)}...${addr.slice(-4)}`;
}
