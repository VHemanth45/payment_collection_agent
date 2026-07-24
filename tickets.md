# Payment Collection Agent Tickets

Source: `spec.md`

These tickets are ordered in dependency order. Each ticket declares its blocking edges and is intended to be small enough for one fresh agent context. Status for every ticket is `ready-for-agent`.

## 01 — Establish the Agent Contract and Deterministic Conversation Shell

**What to build:** Create the public payment-collection agent contract so callers can instantiate an agent, send one user turn at a time, and always receive a deterministic `{"message": str}` response. The initial conversation should safely request an account ID, reject blank/noisy input with an actionable prompt, and keep all behavior testable through the public conversation seam.

**Blocked by:** None — can start immediately.

**Status:** completed

- [x] `Agent.next(user_input)` exists and always returns a dictionary containing a string `message`.
- [x] A new conversation asks for an account ID without exposing internal state names.
- [x] Blank or irrelevant input produces a deterministic prompt for the next required information.
- [x] Conversation state is stored per agent instance and does not leak across separate instances.
- [x] Tests exercise the public `Agent.next` seam rather than relying only on private helpers.

## 02 — Add Account ID Extraction, Validation, and Lookup Flow

**What to build:** Let customers provide account IDs in natural phrasing, normalize valid account IDs, look them up exactly once per accepted ID, and handle malformed, unknown, timeout, and malformed-response lookup outcomes without progressing to verification or payment.

**Blocked by:** 01 — Establish the Agent Contract and Deterministic Conversation Shell.

**Status:** completed

- [x] Account IDs such as `ACC1001`, `acc 1001`, and labeled account phrases are normalized to the accepted canonical form.
- [x] Malformed or ambiguous account IDs are rejected locally with an ACC-style correction prompt and no lookup call.
- [x] A valid account ID triggers exactly one lookup call per accepted account ID.
- [x] Unknown account responses ask the user to check and resend the account ID.
- [x] Lookup timeout, connection, and malformed-response outcomes produce safe deterministic messages and no verification/payment progression.
- [x] Supplying a different account ID before verification replaces the pending account and performs a new lookup.
- [x] Tests assert both required lookup calls and forbidden payment calls.

## 03 — Implement Strict Identity Verification and Lockout

**What to build:** After account lookup succeeds, verify the customer with exact full name plus one accepted secondary factor before revealing any balance. Missing data should guide the user, invalid data should not leak secrets, and three complete failed attempts should close the conversation.

**Blocked by:** 02 — Add Account ID Extraction, Validation, and Lookup Flow.

**Status:** completed

- [x] The agent asks for full name before asking for a secondary factor.
- [x] Full-name comparison is exact after harmless whitespace cleanup only.
- [x] DOB inputs are canonicalized to `YYYY-MM-DD` and impossible dates are rejected without counting as failed verification.
- [x] Ambiguous two-digit-year DOBs are rejected with a request for a four-digit year.
- [x] Aadhaar last four requires exactly four digits and pincode requires exactly six digits with sufficient context.
- [x] Verification passes only on exact full name and one exact secondary-factor match.
- [x] Missing verification data does not increment the retry counter.
- [x] A complete but incorrect verification submission increments one shared verification retry counter.
- [x] Three failed complete verification attempts close the conversation and prevent any later API calls.
- [x] Verification failure responses do not reveal which stored field was wrong.

## 04 — Disclose Balance and Collect Valid Payment Amounts

**What to build:** Once verification succeeds, disclose only the outstanding balance and collect a valid payment amount. Support full-balance requests and common rupee amount formats while rejecting invalid, over-precision, zero, negative, and over-balance amounts locally.

**Blocked by:** 03 — Implement Strict Identity Verification and Lockout.

**Status:** completed

- [x] Balance is disclosed only after successful verification.
- [x] Balance disclosure does not include stored DOB, Aadhaar last four, pincode, or other identity secrets.
- [x] Numeric amounts, comma-separated amounts, currency-symbol amounts, and common rupee wording are parsed into decimal values.
- [x] Full-balance phrases use the looked-up outstanding balance exactly.
- [x] Amounts are rejected if zero, negative, malformed, more than two decimal places, or greater than the outstanding balance.
- [x] Valid amount data supplied before the amount prompt is retained and not requested again after verification.
- [x] Invalid amount responses are deterministic and ask only for a corrected amount.
- [x] No payment API call occurs during amount collection.

## 05 — Collect and Validate Complete Card Details

**What to build:** Collect cardholder name, card number, CVV, and expiry across one or more turns after a valid payment amount exists. Retain valid partial card fields, ask only for missing or invalid fields, and prevent malformed card data from leaving the process.

**Blocked by:** 04 — Disclose Balance and Collect Valid Payment Amounts.

**Status:** completed

- [x] Card number, expiry, CVV, and cardholder name can be supplied in one turn or across multiple turns.
- [x] Card numbers are normalized by removing spaces and hyphens before validation.
- [x] Invalid length or failed Luhn card numbers are rejected before any payment call.
- [x] Expiry supports numeric and natural-language month/year forms and rejects expired or malformed dates.
- [x] CVV accepts three or four digits, including clearly spoken digit sequences.
- [x] Cardholder name is required but is not compared to the account holder.
- [x] Valid partial card fields are retained and not re-requested.
- [x] User-facing card prompts never echo the full card number or CVV.
- [x] Tests prove invalid local card data produces no payment API call.

## 06 — Process Successful Payments and Close Safely

**What to build:** After lookup, verification, amount validation, and card validation all pass, submit the payment payload once, report success with the transaction ID, clear sensitive card fields, and make the completed conversation idempotent.

**Blocked by:** 05 — Collect and Validate Complete Card Details.

**Status:** completed

- [x] The payment API is called only after account lookup, verification, amount validation, and complete card validation succeed.
- [x] The payment payload contains the normalized account ID, two-decimal amount, cardholder name, card number, expiry, and CVV expected by the API contract.
- [x] A successful payment response reports the transaction ID.
- [x] The final recap includes account ID, amount, and status without identity or card secrets.
- [x] Card number, CVV, expiry, and cardholder name are cleared from agent state after the payment attempt.
- [x] Repeated user messages after completion do not trigger another payment call.
- [x] The agent does not claim that the server-side balance changed beyond reporting the successful transaction.

## 07 — Handle Recoverable and Terminal Payment Failures

**What to build:** Map local and API payment failures into deterministic recovery or terminal messages. Allow correction for user-fixable payment failures, enforce a separate payment retry cap, and avoid duplicate charges after ambiguous transport failures.

**Blocked by:** 06 — Process Successful Payments and Close Safely.

**Status:** completed

- [x] API `insufficient_balance` responses ask for a smaller amount while preserving verified status.
- [x] API `invalid_card`, `invalid_cvv`, `invalid_expiry`, and `invalid_amount` responses request the relevant corrected input without echoing sensitive values.
- [x] Local invalid card, expiry, CVV, and amount failures count toward the payment retry cap only when they represent complete user-fixable payment attempts.
- [x] Three failed complete payment attempts close the conversation and prevent later payment calls.
- [x] Unexpected server errors and malformed responses produce safe failure messages without claiming success.
- [x] Timeout or ambiguous submission failures are not automatically retried.
- [x] Card fields are cleared after failed payment attempts, including exceptions.
- [x] Tests assert retry counts, terminal behavior, and no duplicate charge calls.

## 08 — Add Hybrid Free-Form Extraction Without Weakening Determinism

**What to build:** Add the optional schema-bound extractor path on top of the regex fast path so free-form identity, amount, and card inputs are understood more broadly while all validation, verification, API-call eligibility, and final messages remain deterministic.

**Blocked by:** 07 — Handle Recoverable and Terminal Payment Failures.

**Status:** ready-for-agent

- [ ] Regex extraction still runs on every user turn before any extractor call.
- [ ] The extractor is called only when required fields are missing after regex extraction.
- [ ] Only the logical schema group relevant to the current state is requested.
- [ ] Missing extractor fields are represented as null rather than guessed values.
- [ ] Extractor output does not override better regex-derived values.
- [ ] Out-of-order fields recognized by regex are retained without skipping required verification or payment phases.
- [ ] Business logic does not depend on free-form extractor response text.
- [ ] Tests cover schema selection, forced extraction behavior, null missing fields, merge behavior, and deterministic state transitions.

## 09 — Harden Sensitive-Data Handling and Deterministic Messaging

**What to build:** Centralize evaluator-sensitive response wording and enforce redaction rules so identity and payment secrets are never logged, echoed, or exposed through debug/test output.

**Blocked by:** 07 — Handle Recoverable and Terminal Payment Failures.

**Status:** ready-for-agent

- [ ] Balance disclosure, verification failures, payment success, API errors, retry-limit messages, and closed-conversation messages are generated from deterministic templates.
- [ ] No user-facing message contains DOB, Aadhaar last four, pincode, CVV, or full card number.
- [ ] If operational logging exists, card numbers are masked and CVV is never logged.
- [ ] Test failure output and call-trace reports redact card numbers and omit CVV.
- [ ] Closed and completed conversations use deterministic responses and make no further lookup or payment calls.
- [ ] Sensitive-data cleanup is verified for success, recoverable failure, terminal failure, and exception paths.

## 10 — Complete End-to-End Evaluation Coverage and CLI Documentation

**What to build:** Provide the project-level verification harness and user/developer documentation needed to run, demo, and evaluate the payment-collection agent from a clean checkout.

**Blocked by:** 08 — Add Hybrid Free-Form Extraction Without Weakening Determinism; 09 — Harden Sensitive-Data Handling and Deterministic Messaging.

**Status:** ready-for-agent

- [ ] End-to-end tests cover successful full-balance payment, successful partial payment, verification failure lockout, out-of-order input, lookup failures, payment failures, zero-balance behavior, leap-day DOB behavior, repeated post-completion input, blank input, noisy input, and ambiguous input.
- [ ] Tests record expected versus actual state at each turn where useful without asserting brittle private implementation details.
- [ ] Tests assert required API calls, forbidden API calls, and redacted payload reporting.
- [ ] Aggregate evaluation notes cover happy-path success, strict-verification rejection, API-call correctness, retry-limit enforcement, sensitive-data leakage count, and unnecessary re-prompt count.
- [ ] The interactive CLI lets a developer manually run a conversation against the implemented agent.
- [ ] Documentation explains setup, usage, sample conversations, design decisions, testing strategy, and any live API smoke-test prerequisites.
- [ ] The documented behavior remains consistent with `spec.md`.
