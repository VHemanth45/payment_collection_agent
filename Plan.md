# Payment Collection Agent — Build Plan

## 1. Objective and scope

Build a deterministic conversational payment-collection agent exposing exactly:

    class Agent:
        def next(self, user_input: str) -> dict:
            ...

Each call processes one user turn and returns {"message": str}. The agent must:

1. collect and look up an account ID;
2. collect identity data and perform strict in-agent verification;
3. disclose the balance only after verification;
4. collect an amount and complete card details;
5. validate all data before making the payment API call;
6. handle recoverable and terminal failures clearly; and
7. recap and close the conversation.

The implementation should stay deterministic at the control-flow level while using a hybrid extraction strategy:

- fast-path regex and normalization for structurally obvious fields;
- a schema-bound LLM extractor only when the current state still needs information that regex did not recover;
- pure Python validation and business logic after extraction; and
- template-driven user messages for all evaluator-sensitive outputs.

That keeps `next()` behavior testable and repeatable while allowing broader free-form input coverage than regex alone. If the final implementation uses an external LLM API, it must still preserve deterministic state transitions, forced tool-choice extraction, and message-template outputs.

## 2. Proposed repository layout

    agent.py                 # Public Agent class and turn orchestration
    models.py                # Internal state/data structures, if useful
    parsers.py               # Fast-path regex extraction and normalization
    extractor.py             # LLM-backed structured extraction by field group
    validators.py            # Account, identity, amount, card, and date validation
    api_client.py            # HTTP API wrapper and typed result/error handling
    messages.py              # Deterministic response templates
    tests/
      test_agent.py          # Conversation and state tests
      test_parsers.py        # Free-form extraction tests
      test_extractor.py      # LLM schema contract and merge behavior tests
      test_api_client.py     # Request/response and failure mapping tests
    main.py                  # Optional interactive CLI
    README.md                # Setup, usage, sample conversations, evaluation notes
    Plan.md                  # This design/build plan

The first implementation may keep small modules together if that improves clarity, but the public contract must remain in agent.py.

## 3. Architecture

### 3.1 Turn pipeline

Every `next()` call should execute the same turn loop:

1. run fast-path regex extraction over `user_input` for any structurally recognizable fields, regardless of state;
2. merge those extracted values into context slots, including out-of-order fields;
3. if the current state is still missing required information, call the LLM extractor with a schema limited to the plausible group for that state;
4. merge extractor output, treating absent fields as `null` rather than guessed values;
5. run pure Python validation on newly filled fields;
6. ask whether the FSM now has everything needed to advance from the current state;
7. if not, return a template asking for the specific missing piece;
8. if yes, run the state-specific business logic, update counters/flags/results, and transition state; and
9. build the final response from `messages.py` templates and return `{"message": ...}`.

The important boundary is that extraction can be probabilistic, but validation, verification, state transitions, API calls, and user-visible outcome wording are deterministic. Card data offered in the first message may be retained as pending data, but it will never cause payment before account lookup and identity verification.

### 3.2 Explicit states

Use an enum-like internal state:

    WELCOME / NEED_ACCOUNT
    LOOKING_UP_ACCOUNT       (synchronous internal transition)
    NEED_FULL_NAME
    NEED_SECONDARY_FACTOR
    VERIFIED_NEED_AMOUNT
    NEED_CARD_DETAILS
    PROCESSING_PAYMENT       (synchronous internal transition)
    PAYMENT_RETRY
    COMPLETED
    CLOSED_FAILURE

The agent should not expose raw state names to users. Responses should state what is needed next and avoid asking again for fields already accepted.

Suggested transitions:

    start
      -> account detected -> lookup
      -> 200 -> need name/secondary verification
      -> verification pass -> show balance + request amount
      -> valid amount -> request missing card fields
      -> valid card payload -> process payment
      -> success -> completed
      -> retryable payment failure -> payment_retry / need corrected payment input
      -> verification lockout or payment lockout -> closed_failure

Account lookup failures, verification lockout, zero-balance accounts, and unrecoverable transport failures must enter a terminal or safely restartable state rather than reaching payment.

## 4. State and context design

Store only what is needed for the active conversation:

- current state;
- normalized account ID;
- account data returned by lookup, kept in memory only;
- user-provided identity candidates and which factors have been supplied;
- count of failed complete verification attempts;
- count of failed payment attempts for user-fixable payment errors;
- verified flag;
- requested/payment amount as a Decimal;
- transient card fields until the payment call returns;
- outcome/transaction ID for the final recap.

Do not log the state object. Never include DOB, Aadhaar, pincode, CVV, or the full card number in user-facing messages, exceptions, debug output, or test failure output. If any operational logging is added, mask card numbers as `****0366` and never log CVV at all. After a payment attempt, clear card number, CVV, expiry, and cardholder name from agent state, including after exceptions.

If a new account ID is supplied before verification, replace the pending account and look up the new ID. Once payment is processing or the conversation is terminal, explain that the conversation is closed instead of silently mutating the completed record.

## 5. Free-form input extraction

The extraction layer should be hybrid:

- `parsers.py` performs fast-path regex extraction for account IDs, digit groups, ISO-like dates, card-number-shaped strings, CVV-like labels, and expiry-like patterns;
- `extractor.py` runs only when the current state still needs information after fast-path extraction; and
- both layers merge into the same context object so out-of-order information is preserved.

The extractor should not be one giant schema. It should expose one tool schema per logical group:

- `extract_identity(name, dob, aadhaar_last4, pincode)`
- `extract_payment(amount)`
- `extract_card(card_number, cvv, expiry_month, expiry_year, cardholder_name)`

The state machine should always call only the group relevant to the current step, while still merging anything else recognized by the regex layer. Tool-choice should be forced when the LLM extractor is invoked. Missing fields must come back as `null`; the extractor must never infer or fabricate values that are not clearly present in the user message.

### Account ID

- accept ACC1001, acc 1001, and labels such as “account id”;
- remove spaces/hyphens only within an account token and uppercase the ACC prefix;
- validate the resulting format before lookup;
- reject ambiguous or malformed candidates with a correction request;
- call lookup once per accepted account ID.

### Name

- support labels (“name is ...”) and phrases such as “my name is ...”;
- preserve capitalization for matching;
- strip surrounding punctuation and collapse whitespace as input formatting normalization;
- do not case-fold, alias-match, reorder names, or fuzzy-match;
- for a phrase containing a nickname and a full name, prefer the explicitly identified full name.

The comparison remains strict after harmless formatting cleanup: “Nithin Jain” matches, while “nithin jain”, “Nithin”, a nickname, or a reordered name does not.

### Date of birth

Accept labeled or natural forms such as:

- 1990-05-14;
- 14-05-1990;
- 14th May 1990;
- May 14, 90.

Convert to canonical YYYY-MM-DD using an explicit date parser. Use `datetime.date` to reject impossible dates; 1988-02-29 must be accepted because 1988 is a leap year. A two-digit year needs a documented deterministic policy; the safer plan is to reject ambiguous two-digit-year DOBs and ask for a four-digit year rather than silently choosing one. Ambiguous or invalid dates should be requested again and should not count as a failed verification attempt.

### Aadhaar last four and pincode

- detect labels and spaced digits;
- Aadhaar last four requires exactly four digits;
- pincode requires exactly six digits;
- do not infer a six-digit value as Aadhaar or a four-digit value as pincode without context;
- if the user offers either acceptable secondary factor, store it without repeating it back.

### Amount

Support numeric and conversational forms:

- 500, 500.00, and digit groups with commas;
- “a thousand rupees”;
- “clear the full amount” or “pay the outstanding balance”;
- currency symbols and common rupee wording.

Represent the result with `Decimal` and validate it to at most two decimal places. Reject zero, negative, malformed, and ambiguous amounts. A full-balance request uses the looked-up balance exactly. The design choice here is to pre-check `amount <= balance` locally rather than relying on `insufficient_balance` from the API. That gives a faster and more specific correction, reduces unnecessary payment calls, and still preserves API-side validation as a backstop.

### Card fields

Extract cardholder name, card number, CVV, expiry month, and expiry year from labels or prose:

- remove spaces/hyphens from the card number, then validate length and Luhn checksum;
- accept 12/27, 12/2027, “December 2027”, and equivalent labeled forms;
- require a real month and a non-expired card using the current date;
- accept CVV as 3 or 4 digits, including spoken digit sequences such as “one two three”;
- require cardholder name but do not compare it to the account holder because the API explicitly accepts it as-is.

If a turn supplies only some card fields, retain valid fields and ask only for missing or invalid fields. Local Luhn, length, expiry, and CVV checks happen before any payment API call so obviously malformed card input never leaves the process. Avoid echoing the complete card number or CVV in confirmation messages.

## 6. Verification design

Verification is deterministic and occurs only after account lookup succeeds.

Pass condition:

    exact full-name match
    AND
    (exact DOB match OR exact Aadhaar-last-4 match OR exact pincode match)

“Exact” means no case-insensitive matching, fuzzy matching, aliases, partial names, or inferred substitutions. The name comparison is strict `==` after trimming and collapsing surrounding whitespace only. Secondary factors compare as strings after canonicalizing DOB to `YYYY-MM-DD` and stripping harmless digit spacing.

Ask for the full name first, then ask for one secondary factor. If the user has already supplied both, evaluate them at the appropriate phase. Missing values produce guidance, not a failed attempt. Use one shared retry counter for the whole verification phase, not separate counters per field, so the limit cannot be bypassed by alternating wrong name and wrong secondary-factor attempts. A complete but incorrect verification submission increments that shared counter.

Use three failed complete attempts as the retry limit. On the final failure, transition to `CLOSED_FAILURE`, do not reveal which account field was wrong, decline to continue, and prevent further API calls of any kind. A new `Agent()` instance is the supported way to start a new conversation.

On success, disclose only the outstanding balance and payment choices. Never disclose stored DOB, Aadhaar last four, or pincode, either as confirmation or in the final recap.

## 7. API client and tool-call policy

Implement a small API client around the two documented POST endpoints. It should:

- use the exact base URL and JSON payload shapes;
- set JSON content type and a finite request timeout;
- parse successful JSON responses;
- map 404, 422, known error codes, malformed responses, timeouts, and connection failures into typed internal outcomes;
- avoid printing request payloads, especially card fields;
- be injectable or patchable in tests while leaving Agent() usable without setup.

Call policy:

1. /api/lookup-account only after a valid account ID is extracted and never before.
2. Do not call lookup for malformed IDs.
3. /api/process-payment only after account lookup, verification, amount validation, card validation, and all required fields succeed.
4. Do not call process-payment after verification failure, invalid local amount/card data, missing fields, or an account lookup failure.
5. Send Decimal amounts as correctly formatted two-decimal numeric values and include the complete card payload only in the immediate request.

Known payment outcomes:

- success: true: report success and transaction ID, then recap account ID, amount, and status without sensitive identity/card data;
- insufficient_balance: explain the amount exceeds the outstanding balance and allow a smaller amount while retaining verified status;
- invalid_card, invalid_cvv, invalid_expiry: explain the relevant correction, count the attempt as a user-fixable payment retry, and ask for replacement payment details;
- invalid_amount: this should normally be prevented locally; if returned anyway, treat it as a user-fixable payment retry and ask for a corrected amount;
- unexpected 4xx/5xx, malformed response, timeout, or network error: state that payment could not be completed and provide a safe retry or terminal message without claiming success.

Because the supplied server does not persist balances, the agent must rely on the returned transaction ID for success and must not imply that the lookup balance was permanently updated on the server.

## 8. Failure and recovery behavior

Responses should be actionable, phase-specific, and template-based. Anything where wording precision matters should come from `messages.py`, not free LLM generation. That includes:

- balance disclosure;
- verification pass/fail messages;
- transaction success with transaction ID;
- API error messages;
- retry-limit and closed-conversation messages.

Templates may have light deterministic variation, but the agent should not let an LLM freely compose outcome sentences. The evaluator-sensitive facts are the state and payload decisions; the wording that reports them should be fixed.
Responses should be actionable and phase-specific:

- unknown account: “I couldn’t find that account ID. Please check it and send it again.”;
- malformed account: explain the expected ACC####-style format;
- incomplete identity: name the missing category without revealing expected values;
- wrong verification: say the details did not match our records and request the needed factors again without exposing stored values;
- invalid amount: explain the accepted range/precision and ask for a corrected amount;
- invalid card: identify the invalid category, never repeat the secret value, and count only complete user-fixable payment errors toward the payment retry counter;
- API/network failure: distinguish “please retry” from “we cannot safely continue”;
- completed/locked conversation: do not make additional API calls; tell the user to start a new conversation.

Use a separate payment retry counter from verification. Documented user-fixable errors should consume a payment retry:

- local invalid card number;
- local invalid expiry;
- local invalid CVV;
- local invalid amount;
- API `invalid_card`;
- API `invalid_cvv`;
- API `invalid_expiry`;
- API `invalid_amount`.

`insufficient_balance` is still user-fixable, but because the plan already pre-checks against the known balance locally, it should be uncommon; if returned, allow correction without special-casing the whole flow. Set an explicit payment retry cap, preferably three failed complete payment attempts. On exhausting that limit, transition to `CLOSED_FAILURE`, decline further attempts cleanly, and make no additional payment API calls.

The agent should be idempotent from the conversation perspective: after a successful payment, repeated user messages must not trigger another payment call. If a process-payment response is ambiguous or the network times out after submission, do not blindly retry the charge; report that the status could not be confirmed and close or require a separately designed status-check flow.

## 9. Evaluation and automated tests

Build tests with a fake API transport that records calls and returns controlled responses. Correctness is evaluated both by returned messages and by required/forbidden tool-call behavior. Add extractor tests that verify:

- the correct schema group is chosen for the current state;
- tool-choice is forced when extraction is needed;
- missing fields come back as `null`;
- extractor output is merged without overriding better regex-derived values; and
- no business logic depends on free-form LLM response text.

### Required scenarios

1. **Successful full flow**
   - greeting;
   - account ID in prose (“my account is ACC 1001”);
   - exact name;
   - DOB in a natural format;
   - full-balance amount request;
   - card number with spaces, spoken CVV, and textual expiry;
   - assert one lookup, one payment, exact payload fields, transaction ID in response, and no sensitive data leakage.

2. **Successful partial payment**
   - supply amount before the prompt;
   - pay a valid amount below balance;
   - assert the amount is preserved and no unnecessary re-questioning occurs.

3. **Verification failure**
   - wrong name/secondary factor for three complete attempts;
   - assert no payment call, retry count, terminal lockout, and no account secrets in responses.

4. **Verification partial/out-of-order input**
   - give name, DOB, pincode, amount, and card data across unexpected turns;
   - assert data is retained but phases are not skipped.

5. **Account lookup failures**
   - malformed ID, 404 account, timeout, malformed JSON;
   - assert no verification/payment progression and actionable messages.

6. **Payment failures**
   - invalid Luhn card;
   - expired card;
   - invalid CVV;
   - invalid amount returned locally and by API backstop;
   - API insufficient_balance;
   - unexpected 5xx/network error;
   - assert correct retry/terminal behavior, retry-cap enforcement, and no duplicate charge calls.

7. **Edge cases**
   - ACC1003 with zero balance;
   - ACC1004 DOB 1988-02-29 accepted;
   - nearby invalid leap date rejected;
   - invalid precision, zero, negative, and over-balance amounts;
   - account/name case mismatch rejected;
   - full card data in one free-form turn;
   - repeated messages after completion;
   - blank, noisy, or ambiguous input.

### Metrics

For each scripted conversation, record:

- conversation completion status;
- expected vs. actual state at each turn;
- required API calls made and forbidden API calls avoided;
- request payload correctness, with card secrets redacted in reports;
- verification precision: no false acceptance of mismatched identity;
- retry-limit enforcement;
- payment outcome classification correctness;
- sensitive-data leakage count;
- unnecessary re-prompt count.

Report aggregate happy-path success rate, strict-verification rejection rate, API-call correctness, and failure-message/actionability coverage. Replay paraphrased personas to check that equivalent natural-language inputs produce the same state transitions.

## 10. Implementation sequence

1. Replace placeholder main.py behavior with a small interactive loop, while keeping the public agent in agent.py.
2. Add internal state models and response helpers.
3. Implement pure validators/parsers first and test them independently.
4. Implement the API client and fake transport tests.
5. Implement the state machine and identity verification.
6. Add payment collection, sensitive-data cleanup, and failure mapping.
7. Add end-to-end conversation tests and call-trace assertions.
8. Add `messages.py` templates and assert that evaluator-sensitive responses come from deterministic builders.
9. Write README setup/run instructions, sample conversations, architecture summary, and evaluation instructions.
10. Run the complete test suite and a manual CLI smoke test against mocked APIs; use the live API only for an explicit integration smoke test if network access is available.

## 11. Tradeoffs and future improvements

### Chosen tradeoffs

- **Hybrid extraction instead of rules alone:** regex handles obvious structure cheaply and deterministically, while a schema-bound extractor covers messier phrasing. The tradeoff is dependency and integration complexity, which is contained by keeping all business logic outside the model.
- **In-memory state:** satisfies the required single-agent conversational interface and avoids persisting sensitive data, at the cost of process-loss recovery.
- **Three complete verification retries with one shared counter:** closes the bypass where a user could rotate between bad sub-fields.
- **Three complete payment retries with a separate counter:** allows correction of card entry mistakes without weakening verification controls.
- **Local validation before API calls:** gives fast, clear corrections and reduces invalid requests, while relying on the API as the final authority for payment checks.
- **Template-driven outcome messages:** preserves evaluator-facing determinism and prevents extractor variability from leaking into success or failure wording.

### Future improvements

- Add confidence scoring and extractor fallback routing for especially ambiguous turns.
- Add secure tokenization/provider-hosted card collection so raw card data never enters application memory.
- Add authenticated session storage with encryption, redaction, audit logging, and rate limiting.
- Add payment-status reconciliation for ambiguous network outcomes.
- Add localization, accessibility-oriented responses, and broader multilingual date/amount parsing.

## 12. Definition of done

The build is complete when:

- Agent().next() matches the required interface;
- all happy-path and failure-path tests pass;
- payment cannot be called before successful verification;
- strict name plus secondary-factor matching is enforced;
- free-form examples in the prompt are handled;
- all API outcomes have actionable responses;
- raw card/security data is not logged or echoed and is cleared after payment attempts;
- README contains setup, CLI usage, sample conversations, design decisions, and evaluation instructions; and
- Plan.md remains an accurate description of the implemented behavior.
