## Problem Statement

Users need a conversational payment-collection agent that can safely collect payments against an outstanding account balance. The agent must guide the user through account lookup, identity verification, balance disclosure, payment amount selection, card collection, and payment completion without exposing sensitive data or allowing payment before verification.

The current project only has a placeholder entry point. It needs a deterministic agent implementation with a stable public interface, predictable state transitions, strict verification rules, clear failure handling, and tests that prove the agent never makes unsafe API calls.

## Solution

Build a deterministic payment-collection agent with a public `Agent.next(user_input: str) -> dict` interface. Each call processes one user turn and returns a response shaped as `{"message": str}`.

The agent will use a state machine for control flow, pure Python validation for account, identity, amount, and card data, and deterministic message templates for user-visible outcomes. Free-form input support will be handled with a hybrid extraction strategy: regex and normalization first, then a schema-bound extractor only when required information is still missing for the current state.

The agent will look up the account only after receiving a valid account ID, verify the user's exact full name plus one accepted secondary factor, disclose the balance only after verification, collect a valid payment amount and complete card details, call the payment API only after all local checks pass, and close the conversation with a recap or clear failure message.

## User Stories

1. As a customer with an outstanding balance, I want to provide my account ID conversationally, so that I can start the payment flow without following a rigid form.
2. As a customer, I want the agent to accept account IDs with harmless spacing or casing differences, so that small formatting differences do not block me.
3. As a customer, I want malformed account IDs to be rejected with a clear correction prompt, so that I know how to fix my input.
4. As a customer, I want the agent to look up only valid account IDs, so that invalid data is not sent to the account API.
5. As a customer, I want the agent to tell me when an account cannot be found, so that I can check and resend the correct account ID.
6. As a customer, I want to replace the pending account ID before verification, so that I can correct a mistaken account selection.
7. As a customer, I want the agent to ask for my full name before revealing account details, so that my account information is protected.
8. As a customer, I want identity verification to require an exact full-name match, so that account access is not granted from partial or fuzzy matches.
9. As a customer, I want the agent to ask for one secondary identity factor, so that verification is secure without requiring every possible identifier.
10. As a customer, I want to verify with date of birth, Aadhaar last four, or pincode, so that I can use the available factor that is easiest for me.
11. As a customer, I want valid natural-language DOB formats to be accepted, so that I can type dates naturally.
12. As a customer, I want impossible or ambiguous DOBs to be rejected without counting as a failed verification attempt, so that input formatting mistakes do not lock me out.
13. As a customer, I want Aadhaar last four and pincode to be validated by length and context, so that unrelated digit strings are not misused.
14. As a customer, I want the agent to avoid repeating sensitive identity factors, so that my private details are not exposed in the chat.
15. As a customer, I want failed verification messages to avoid revealing which field was wrong, so that attackers cannot enumerate account records.
16. As a customer, I want a limited number of complete verification attempts, so that the system prevents repeated guessing.
17. As a customer, I want the conversation to close after verification lockout, so that no payment or account action can occur after too many failed attempts.
18. As a verified customer, I want to see the outstanding balance, so that I can decide how much to pay.
19. As a verified customer, I want to pay the full outstanding balance with a phrase like "pay the full amount", so that I do not need to retype the amount.
20. As a verified customer, I want to pay a partial valid amount, so that I can make a smaller payment against my balance.
21. As a verified customer, I want amount inputs with commas, decimals, currency symbols, or common rupee wording to be understood, so that normal payment language works.
22. As a verified customer, I want zero, negative, malformed, over-precision, and over-balance amounts to be rejected locally, so that I get immediate correction guidance.
23. As a verified customer, I want the agent to preserve valid information supplied early, so that I do not need to repeat details already given.
24. As a verified customer, I want the agent to avoid skipping required phases even when I provide out-of-order details, so that the flow remains safe.
25. As a verified customer, I want to provide card number, expiry, CVV, and cardholder name in one turn or across multiple turns, so that I can complete payment naturally.
26. As a verified customer, I want card numbers with spaces or hyphens to be normalized, so that common formatting is accepted.
27. As a verified customer, I want invalid card numbers to be caught before an API call, so that obviously bad card data is not submitted.
28. As a verified customer, I want expired or malformed expiry dates to be rejected, so that payment attempts use valid card data.
29. As a verified customer, I want CVV values to support labeled digits or spoken digit sequences, so that common input styles work.
30. As a verified customer, I want the agent to ask only for missing or invalid card fields, so that valid card fields do not need to be re-entered.
31. As a verified customer, I want the agent to avoid echoing full card numbers or CVVs, so that sensitive payment data stays private.
32. As a verified customer, I want the payment API to be called only after account lookup, verification, amount validation, and card validation succeed, so that unsafe payment attempts cannot occur.
33. As a verified customer, I want successful payment confirmation to include the transaction ID, so that I have a clear reference for the payment.
34. As a verified customer, I want the final recap to include account ID, amount, and status without identity or card secrets, so that I can understand the result safely.
35. As a verified customer, I want insufficient-balance responses to let me choose a smaller amount, so that I can recover without restarting.
36. As a verified customer, I want card-related API failures to request corrected payment details, so that I can retry recoverable payment errors.
37. As a verified customer, I want a payment retry limit, so that repeated failed payment attempts close safely.
38. As a verified customer, I want network or ambiguous payment failures to avoid duplicate charges, so that the agent does not blindly retry a possibly submitted payment.
39. As a customer, I want completed or locked conversations to reject further action, so that repeated messages cannot trigger duplicate lookups or payments.
40. As a developer, I want deterministic state transitions, so that the agent can be tested reliably.
41. As a developer, I want extraction separated from validation and business logic, so that probabilistic parsing cannot control payment decisions.
42. As a developer, I want user-visible outcome messages to come from templates, so that evaluator-sensitive wording is predictable.
43. As a developer, I want API behavior represented as typed outcomes, so that failures are mapped consistently.
44. As a developer, I want the API client to be injectable or patchable, so that tests can record calls without using the live service.
45. As a developer, I want tests to assert forbidden API calls, so that security-sensitive ordering is enforced.
46. As a developer, I want sensitive values redacted from logs, messages, and test reports, so that failures do not leak payment or identity data.
47. As a developer, I want card fields cleared after payment attempts, so that raw card data is not retained longer than necessary.
48. As an evaluator, I want scripted conversations to produce stable results, so that happy paths and failure paths can be judged consistently.

## Implementation Decisions

- The public contract is a single `Agent` class with a `next(user_input: str) -> dict` method. The returned dictionary always contains a `message` string.
- The control flow is an explicit finite state machine with states for account collection, account lookup, full-name collection, secondary-factor collection, verified amount collection, card collection, payment processing, payment retry, completion, and closed failure.
- Internal lookup and payment-processing states are synchronous transitions. They should not expose raw state names to users.
- The agent stores only conversation-local state: current state, normalized account ID, looked-up account data, supplied identity candidates, failed verification attempts, failed payment attempts, verified flag, requested amount, transient card fields, and final payment outcome.
- Account data and card data are retained only as needed for the active conversation. Card number, CVV, expiry, and cardholder name are cleared after any payment attempt, including exceptions.
- The extraction pipeline runs regex and normalization over every user turn first, regardless of state, so out-of-order structured values can be retained.
- A schema-bound extractor may run only when required fields are still missing after regex extraction. The extractor is limited to the logical group relevant to the current state.
- Extractor schemas are separated by identity, payment amount, and card details. Missing fields must be represented as null, and the extractor must not infer values that are not clearly present.
- Extraction output never makes business decisions. Validation, verification, state transitions, API call eligibility, and final wording are implemented deterministically.
- Account IDs accept normal forms such as `ACC1001`, spacing within the token, and labeled account phrases. Accepted IDs are normalized before lookup and validated before any API call.
- Full-name matching is strict after harmless whitespace trimming and collapsing. There is no case-insensitive matching, alias matching, fuzzy matching, partial matching, or name reordering.
- DOB inputs are canonicalized to `YYYY-MM-DD` with real date validation. Ambiguous two-digit-year DOBs are rejected and re-requested with a four-digit-year instruction.
- Aadhaar last four must be exactly four digits. Pincode must be exactly six digits. Numeric strings are not assigned to either factor without sufficient context.
- Verification passes only when the exact full name matches and at least one secondary factor matches exactly.
- Missing verification data produces guidance and does not count as a failed attempt. A complete but incorrect verification submission increments one shared verification retry counter.
- Verification permits three failed complete attempts. After the third failure, the agent enters a closed-failure state, reveals no record details, and performs no further API calls.
- Balance disclosure occurs only after successful verification. Stored DOB, Aadhaar last four, and pincode are never disclosed.
- Amounts are represented as `Decimal` values and validated for positive value, at most two decimal places, and not exceeding the outstanding balance.
- Full-balance requests use the looked-up balance exactly. The agent pre-checks `amount <= balance` locally before payment.
- Card numbers are normalized by removing spaces and hyphens, then validated for length and Luhn checksum before any payment call.
- Expiry accepts numeric and natural-language month/year forms, requires a real month, and must not be expired relative to the current date.
- CVV accepts three or four digits, including clearly spoken digit sequences.
- Cardholder name is required for the payment payload but is not compared to the account holder name.
- User-facing messages are built from deterministic templates, especially balance disclosure, verification failures, transaction success, API errors, retry limits, and closed-conversation messages.
- The account lookup API is called only after a valid normalized account ID is available. It is called once per accepted account ID.
- The payment API is called only after lookup success, verification success, amount validation, card validation, and required card fields are complete.
- Payment success reports the transaction ID and a safe recap containing account ID, payment amount, and status.
- Known payment API errors are mapped to user-fixable responses where appropriate. Unexpected server, malformed-response, timeout, and connection failures do not claim success.
- The agent does not imply that the server-side balance was updated unless the payment API returns a successful transaction ID.
- After successful completion, repeated user messages must not trigger another payment call.
- If a payment submission times out or has ambiguous status, the agent must not automatically retry the charge.

## Testing Decisions

- The highest-value test seam is the public conversation interface: instantiate the agent, send user turns through `next`, assert returned messages, final state, and API call traces.
- Lower-level seams are used where isolation is valuable: parsers and validators for deterministic normalization rules, extractor contract tests for schema and merge behavior, and API client tests for request/response mapping.
- Tests should assert external behavior rather than implementation details. Important behavior includes messages, state progression, required API calls, forbidden API calls, payload correctness, retry limits, terminal states, and sensitive-data leakage.
- The API should be tested through a fake transport or injectable client that records lookup and payment calls and returns controlled outcomes.
- Successful full-flow tests should cover account ID in prose, exact-name verification, natural DOB parsing, full-balance payment, card number normalization, spoken CVV, textual expiry, one lookup call, one payment call, transaction ID reporting, and no sensitive-data echo.
- Successful partial-payment tests should verify that a valid amount supplied before the amount prompt is retained and reused without unnecessary re-prompting.
- Verification failure tests should cover three complete failed attempts, lockout, no payment calls, no account-secret disclosure, and rejection of later user messages.
- Out-of-order input tests should verify that early valid fields are retained but account lookup, verification, balance disclosure, and payment still occur only in the correct order.
- Account lookup failure tests should cover malformed account IDs, unknown accounts, timeouts, malformed responses, no verification progression, and no payment calls.
- Payment failure tests should cover invalid Luhn card numbers, expired cards, invalid CVV, invalid local amounts, API invalid-amount backstop, insufficient balance, unexpected server errors, network errors, retry behavior, retry cap enforcement, and duplicate-charge prevention.
- Edge-case tests should cover zero-balance accounts, leap-day DOBs, invalid leap dates, amount precision, zero or negative amounts, over-balance amounts, case-sensitive name mismatch, full card data in one free-form turn, completed conversation repeat input, blank input, noisy input, and ambiguous input.
- Extractor tests should verify that the correct schema group is selected for the current state, tool choice is forced, missing fields return null, extractor output does not override better regex-derived values, and business logic does not depend on free-form LLM text.
- Test reports and assertion messages must redact card numbers and must never include CVV.
- Prior art is currently limited because the repository has only a placeholder implementation. The initial suite should establish the conversation seam as the primary precedent for future changes.

## Out of Scope

- Persistent conversation storage across process restarts.
- Authenticated user sessions beyond in-agent identity verification.
- Secure card tokenization or provider-hosted card collection.
- Balance mutation or reconciliation beyond the payment API success response.
- Automatic duplicate-charge reconciliation after ambiguous network failures.
- Admin dashboards, audit-log viewers, or operational reporting.
- Multilingual support beyond the explicitly supported natural-language date, amount, and card formats.
- Fuzzy identity matching, nickname matching, alias matching, case-insensitive matching, or partial-name matching.
- Revealing stored identity values as hints during verification.
- Continuing a locked or completed conversation in the same `Agent` instance.
- Live API integration tests unless network access and service credentials are explicitly available.

## Further Notes

The key design constraint is that extraction may be probabilistic, but payment eligibility must not be. The implementation should keep all security-sensitive decisions in deterministic Python code and use templates for evaluator-sensitive responses.

The proposed testing seam is the public `Agent.next` interface because it verifies the same behavior a caller depends on: turn-by-turn conversation output and whether API calls were or were not made. Parser, validator, extractor, and API client tests should support that seam rather than replace it.

If an issue tracker is configured later, this spec should be published there with the `ready-for-agent` triage label. No issue-tracker configuration is present in the current workspace, so this request is fulfilled by creating this local spec file.
