IDManagerAgent: Technical Architecture Guide
Component: core/id_manager_agent.py <br />
Version: 5.0 (Pure Identity Service) <br />
Status: Production Ready, Cloud Native
1. Introduction: The System's Notary
In a Sovereign Intelligent Organization (SIO) comprised of dozens or thousands of autonomous agents, the question of "who is who" is not trivial; it is the absolute bedrock of security and trust. The IDManagerAgent is the component that answers this question.
Its core philosophy is to do one thing and do it with cryptographic certainty. That one thing is to serve as the SIO's centralized, secure Identity Provider and Notary.
It provides new, unique cryptographic identities (Ethereum wallets) to agents upon authorized request.
It verifies the identity of any agent by validating digital signatures.
It does not enforce policy on who can receive an identity. That is a higher-level governance decision made by agents like Mastermind. The IDManagerAgent simply executes authorized requests, acting as an incorruptible digital passport office.
2. Core Architecture: Secure, Auditable, and Cloud-Native
The architecture is designed for maximum security and auditability, with a clean separation of public and private data, making it suitable for production deployment on Google Cloud.
2.1. The Public Ledger (wallet_ledger.json)
This file is the authoritative public record of all identities managed by the system. It is a simple JSON file that stores non-sensitive metadata for every wallet. It is designed to be easily readable and auditable.
Example wallet_ledger.json:
{
  "wallets": {
    "0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B": {
      "public_address": "0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B",
      "entity_id": "mastermind_prime",
      "secret_id": "mindx--wallet--mastermind-prime--9aeC9B",
      "status": "ACTIVE",
      "created_at_utc": "2023-10-27T10:00:00.123456",
      "requester_agent_id": "system_bootstrap"
    },
    "0x1234...": {
      "public_address": "0x1234...",
      "entity_id": "bdi-worker-alpha",
      "secret_id": "mindx--wallet--bdi-worker-alpha--C4a8e2",
      "status": "DEPRECATED",
      "created_at_utc": "...",
      "requester_agent_id": "mastermind_prime"
    }
  }
}
Use code with caution.
Json
2.2. The Secret Store (Google Secret Manager)
Private keys are never stored on the local filesystem. They are stored exclusively in a dedicated, secure backend. The implementation is abstracted to support different backends, but the primary target for v1.0 is Google Cloud Secret Manager.
Secret Naming: Secrets are named using a strict, IAM-friendly convention: mindx--wallet--{safe_entity_id}--{last_6_of_address}. This allows for granular access control policies in Google Cloud (e.g., "allow the FinancialMind service account to access secrets matching mindx--wallet--financial*").
Abstraction: A private _GoogleSecretManagerBackend class encapsulates all direct google-cloud-secretmanager client library calls. A _MockSecretManagerBackend is used for local development, allowing the agent to function without needing cloud credentials.
This dual-component design—a public JSON ledger for metadata and a secure cloud backend for secrets—provides the ideal balance of auditability and security.
3. Capabilities and API
The IDManagerAgent exposes a lean, powerful, and secure API for other agents. All interactions should be performed via the await IDManagerAgent.get_instance() singleton factory.
async create_new_wallet(entity_id: str, requester_id: str) -> Dict
This is the primary method for provisioning a new identity.
Workflow:
It receives a request to create a wallet for a specific entity_id (e.g., "bdi-worker-gamma").
The requester_id (e.g., "mastermind_prime") is logged for auditing purposes.
It first checks the ledger to see if an ACTIVE wallet for that entity_id already exists. If so, it returns the existing identity (idempotency).
It generates a new Ethereum account (eth_account.Account.create()).
It generates a unique secret_id for the Google Secret Manager.
It calls the secrets backend to create the secret and store the private key.
Only upon successful storage of the key does it add the new IdentityRecord to the wallet_ledger.json and save it.
It returns a dictionary containing the status and the new identity record.
Example Usage (from another agent, e.g., Mastermind):
id_manager = await IDManagerAgent.get_instance()
result = await id_manager.create_new_wallet(
    entity_id="bdi-worker-delta",
    requester_id="mastermind_prime"
)

if result.get("status") == "SUCCESS":
    new_identity = result.get("data")
    print(f"New agent wallet created: {new_identity['public_address']}")
Use code with caution.
Python
async get_account_for_signing(public_address: str) -> Optional[Account]
This method securely provides a ready-to-use Account object without ever exposing the private key to the calling agent.
Workflow:
It looks up the public_address in the local ledger to find its corresponding secret_id.
It calls the secrets backend to access the latest version of that secret.
It retrieves the private key payload directly from the backend.
It instantiates an eth_account.Account object in memory using Account.from_key().
It returns this fully-functional Account object.
Example Usage:
id_manager = await IDManagerAgent.get_instance()
my_account = await id_manager.get_account_for_signing(self.public_address)

if my_account:
    message = "This is a signed directive."
    signature = my_account.sign_message(encode_defunct(text=message))
    # Now the agent can use signature.signature.hex()
Use code with caution.
Python
verify_signature(public_address: str, message: str, signature: str) -> bool
This is the core notary function. It allows any agent to verify the authenticity of a message from another agent.
Workflow:
It takes the public address of the purported signer, the original message, and the hexadecimal signature string.
It uses the eth_account.Account.recover_message() function to derive the public address of the key that signed the message.
It performs a case-insensitive comparison between the recovered address and the provided public_address.
It returns True if they match, False otherwise.
Example Usage (from a verifier, e.g., CoordinatorAgent):
# An interaction requires a signature from 'mastermind_prime'
directive_payload = '{"action": "deploy_service", "service_name": "sentinel_api"}'
signature_from_mastermind = "0x..." # The signature provided by Mastermind

id_manager = await IDManagerAgent.get_instance()
is_authentic = id_manager.verify_signature(
    public_address="0xMastermindAddress...",
    message=directive_payload,
    signature=signature_from_mastermind
)

if is_authentic:
    print("Directive is authentic. Proceeding with deployment.")
else:
    print("SECURITY ALERT: Invalid signature detected!")
Use code with caution.
Python
This cryptographic verification is the foundation of trust within the SIO, enabling secure, auditable, and non-repudiable communication between all agents.
