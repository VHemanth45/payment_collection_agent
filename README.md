# Payment Collection Agent

A deterministic, stateful payment-collection conversation agent. The public
interface is `Agent.next(user_input) -> {"message": str}`. Account lookup and
payment clients are injectable, so the same conversation can be tested without
network access.

## Setup

This project uses Python 3.14+ and has one runtime dependency, Pydantic 2.

```bash
uv sync
```

The equivalent direct setup is:

```bash
python -m pip install 'pydantic>=2,<3'
```

## Run the CLI

Run the CLI directly after setup:

```bash
python main.py

```

The CLI automatically uses the following flow when a field needs extraction:

1. Deterministic parsing runs first.
2. Local Ollama is tried automatically for missing or unclear fields.
3. Claude is tried when `ANTHROPIC_API_KEY` is configured and Ollama is
   unavailable.
4. If neither provider is available, the deterministic result is used without
   requiring any extra command or configuration.

Extraction is silent in the CLI. Deterministic parsing handles simple inputs;
an optional provider is consulted only for genuinely unstructured language.


The following sample conversations demonstrate successful payments, natural
language field extraction, an invalid card-number retry, and out-of-order
identity information. Transaction IDs are illustrative.

### Example 1: Natural-language payment details

```text
Payment Collection Agent
Type :quit to exit.
Agent: Let's get started. What is your account ID? (Example: ACC1002)
You: acc1001
Agent: Thanks. What is your full name exactly as it appears on the account?
You: it's Nithin, Nithin Jain
Agent: To verify you, provide one verification detail: DOB (YYYY-MM-DD), Aadhaar last four digits, or your six-digit pincode. You can send just the digits.
You: born 14th May 1990
Agent: Your identity has been verified. Your outstanding balance is ₹1250.75. How much would you like to pay? Enter an amount such as ₹100, or say 'pay the full balance'.
You: 500
Agent: Got it — your payment amount is recorded. What name should appear on the card?
You: hemanth
Agent: What is the card number? Enter 12–19 digits.
You: 4532015112830366
Agent: What is the CVV? Enter 3 or 4 digits.
You: CVV is one two three
Agent: What is the card expiry date? Use MM/YYYY.
You: "expires December 2027"
Agent: Payment successful. Transaction ID: txn_****9374_tki95ad. Account ID: ACC1001. Amount: ₹500.00. Status: successful.
```

### Example 2: Invalid card number followed by a retry

```text
Payment Collection Agent
Type :quit to exit.
Agent: Let's get started. What is your account ID? (Example: ACC1002)
You: acc1002
Agent: Thanks. What is your full name exactly as it appears on the account?
You: Rajarajeswari Balasubramaniam
Agent: To verify you, provide one verification detail: DOB (YYYY-MM-DD), Aadhaar last four digits, or your six-digit pincode. You can send just the digits.
You: 9876
Agent: Your identity has been verified. Your outstanding balance is ₹540.00. How much would you like to pay? Enter an amount such as ₹100, or say 'pay the full balance'.
You: 500
Agent: Got it — your payment amount is recorded. What name should appear on the card?
You: Nithin
Agent: What is the card number? Enter 12–19 digits.
You: 4532015112830361
Agent: Please provide a valid card number.
You: 4532015112830366
Agent: What is the CVV? Enter 3 or 4 digits.
You: 123
Agent: What is the card expiry date? Use MM/YYYY.
You: dec 2028
Agent: Payment successful. Transaction ID: txn_****8488_p74e3t6. Account ID: ACC1002. Amount: ₹500.00. Status: successful.
```

### Example 3: Out-of-order identity information without re-prompting

```text
Payment Collection Agent
Type :quit to exit.
Agent: Let's get started. What is your account ID? (Example: ACC1002)
You: My name is Nithin Jain and account id is ACC1001
Agent: To verify you, provide one verification detail: DOB (YYYY-MM-DD), Aadhaar last four digits, or your six-digit pincode. You can send just the digits.
You: 4321
Agent: Your identity has been verified. Your outstanding balance is ₹1250.75. How much would you like to pay? Enter an amount such as ₹100, or say 'pay the full balance'.
You: 500
Agent: Got it — your payment amount is recorded. What name should appear on the card?
You: hemanth
Agent: What is the card number? Enter 12–19 digits.
You: 4532015112830366
Agent: What is the CVV? Enter 3 or 4 digits.
You: 123
Agent: What is the card expiry date? Use MM/YYYY.
You: dec 2029
Agent: Payment successful. Transaction ID: txn_****0363_rbi8yaa. Account ID: ACC1001. Amount: ₹500.00. Status: successful.
```

### Example 4: Verification-factor retry

```text
Payment Collection Agent
Type :quit to exit.
Agent: Let's get started. What is your account ID? (Example: ACC1002)
You: yeah my account number is ACC1001 I think
Agent: Thanks. What is your full name exactly as it appears on the account?
You: it's Nithin, Nithin Jain
Agent: To verify you, provide one verification detail: DOB (YYYY-MM-DD), Aadhaar last four digits, or your six-digit pincode. You can send just the digits.
You: Aadhaar ends with 9876, shall I give pincode instead?
Agent: To verify you, provide one verification detail: DOB (YYYY-MM-DD), Aadhaar last four digits, or your six-digit pincode. You can send just the digits.
You: Aadhaar ends with 4321, shall I give pincode instead?
Agent: Your identity has been verified. Your outstanding balance is ₹1250.75. How much would you like to pay? Enter an amount such as ₹100, or say 'pay the full balance'.
You: 500
Agent: Got it — your payment amount is recorded. What name should appear on the card?
You: hemanth
Agent: What is the card number? Enter 12–19 digits.
You: the card number is 4532 0151 1283 0366
Agent: What is the CVV? Enter 3 or 4 digits.
You: 123
Agent: What is the card expiry date? Use MM/YYYY.
You: 12/2029
Agent: Payment successful. Transaction ID: txn_****5339_zad021s. Account ID: ACC1001. Amount: ₹500.00. Status: successful.
```

### Example 5: Out-of-order account, pincode, and payment details

```text
Payment Collection Agent
Type :quit to exit.
Agent: Let's get started. What is your account ID? (Example: ACC1002)
You: hey I think my account is ACC1004 but pincode is 400004 too
Agent: Thanks. What is your full name exactly as it appears on the account?
You: my name is Rahul Mehta
Agent: Your identity has been verified. Your outstanding balance is ₹3200.50. How much would you like to pay? Enter an amount such as ₹100, or say 'pay the full balance'.
You: 500
Agent: Got it — your payment amount is recorded. What name should appear on the card?
You: hemanth
Agent: What is the card number? Enter 12–19 digits.
You: 4532015112830366
Agent: What is the CVV? Enter 3 or 4 digits.
You: 123
Agent: What is the card expiry date? Use MM/YYYY.
You: 12/2030
Agent: Payment successful. Transaction ID: txn_****7642_j0ldfd6. Account ID: ACC1004. Amount: ₹500.00. Status: successful.
```

### Example 6: LLM fallback for a natural-language DOB

```text
Payment Collection Agent
Type :quit to exit.
Agent: Let's get started. What is your account ID? (Example: ACC1002)
You: hi so I bank with you guys, my account should be ACC1002 I believe
Agent: Thanks. What is your full name exactly as it appears on the account?
You: you can call me Raja but my full name is Rajarajeswari Balasubramaniam
Agent: To verify you, provide one verification detail: DOB (YYYY-MM-DD), Aadhaar last four digits, or your six-digit pincode. You can send just the digits.
You: for verification, I was born in the November of eighty-five, the 23rd
Agent: Your identity has been verified. Your outstanding balance is ₹540.00. How much would you like to pay? Enter an amount such as ₹100, or say 'pay the full balance'.
You: 100
Agent: Got it — your payment amount is recorded. What name should appear on the card?
You: hemanth
Agent: What is the card number? Enter 12–19 digits.
You: the card number is 4532 0151 1283 0366
Agent: What is the CVV? Enter 3 or 4 digits.
You: CVV is one two three
Agent: What is the card expiry date? Use MM/YYYY.
You: expires December 2027
Agent: Payment successful. Transaction ID: txn_****7607_zlozaqj. Account ID: ACC1002. Amount: ₹100.00. Status: successful.
```

### Example 7: Invalid CVV retry limit

Invalid CVV values are rejected locally with the `invalid_cvv` reason. The
valid card number is retained while the user retries the CVV. After three
invalid attempts, the conversation closes without calling the payment API.

```text
Payment Collection Agent
Type :quit to exit.
Agent: Let's get started. What is your account ID? (Example: ACC1002)
You: acc1001
Agent: Thanks. What is your full name exactly as it appears on the account?
You: Nithin Jain
Agent: To verify you, provide one verification detail: DOB (YYYY-MM-DD), Aadhaar last four digits, or your six-digit pincode. You can send just the digits.
You: 4321
Agent: Your identity has been verified. Your outstanding balance is ₹1250.75. How much would you like to pay? Enter an amount such as ₹100, or say 'pay the full balance'.
You: 500
Agent: Got it — your payment amount is recorded. What name should appear on the card?
You: hemanth
Agent: What is the card number? Enter 12–19 digits.
You: 4532015112830366
Agent: What is the CVV? Enter 3 or 4 digits.
You: 12435
Agent: Payment failed (invalid_cvv): please provide a valid CVV.
You: 125487
Agent: Payment failed (invalid_cvv): please provide a valid CVV.
You: 45226
Agent: I couldn't complete the payment after three attempts. This conversation is now closed.
```

### Example 8: Expired card

An expired card is rejected locally with the `invalid_expiry` reason. The
conversation remains available for a corrected expiry date until the payment
retry limit is reached.

```text
Payment Collection Agent
Type :quit to exit.
Agent: Let's get started. What is your account ID? (Example: ACC1002)
You: acc1001
Agent: Thanks. What is your full name exactly as it appears on the account?
You: Nithin Jain
Agent: To verify you, provide one verification detail: DOB (YYYY-MM-DD), Aadhaar last four digits, or your six-digit pincode. You can send just the digits.
You: 4321
Agent: Your identity has been verified. Your outstanding balance is ₹1250.75. How much would you like to pay? Enter an amount such as ₹100, or say 'pay the full balance'.
You: 500
Agent: Got it — your payment amount is recorded. What name should appear on the card?
You: hemanth
Agent: What is the card number? Enter 12–19 digits.
You: 4532015112830366
Agent: What is the CVV? Enter 3 or 4 digits.
You: 123
Agent: What is the card expiry date? Use MM/YYYY.
You: 12/2024
Agent: Payment failed (invalid_expiry): please provide a valid expiry date.
```

Use `:quit` to leave. The CLI requires network access to the configured
service and a valid test account/card approved for that environment. No live
smoke test is run by the local test suite; the evaluation runner uses injected
test clients instead.

## Testing and evaluation

Run all unit, security, hybrid-extraction, and end-to-end tests from a clean
checkout with:

```bash
python -m unittest discover -s tests -v
```

Run the aggregate evaluation notes with:

```bash
python -m evaluation
```

The end-to-end suite covers full and partial payments, strict verification and
lockout, out-of-order input, lookup and payment failures, zero balances,
leap-day dates, repeated completion input, blank/noisy/ambiguous input, API
call ordering, and redacted payload reports. Assertions use public responses
and observable fake-service calls; private state names are not part of the
evaluation contract.

## Design decisions

- The finite-state conversation keeps account lookup, verification, balance
  disclosure, amount validation, card validation, and payment submission in a
  fixed safe order.
- Regex/normalization runs first on every turn. The optional schema-bound
  extractor can fill missing fields, but cannot decide verification or payment
  eligibility.
- When deterministic parsing leaves required fields missing, an injected
  extractor is invoked for the relevant schema group. The CLI does not make
  unsolicited model/network calls; provide an extractor client explicitly when
  LLM fallback is configured.
- Full name matching is exact after whitespace cleanup. One exact DOB, Aadhaar
  suffix, or pincode is also required. Three complete failures close the
  conversation.
- Amounts use `Decimal`; card numbers are normalized and Luhn checked; expiry
  and CVV are validated locally before payment.
- User-facing templates never echo identity secrets, CVVs, or full card
  numbers. Reports mask card numbers and omit CVVs.
- Card data is cleared after every payment attempt, including exceptions, and
  completed or ambiguous conversations do not automatically submit again.

See [`spec.md`](spec.md) for the full behavioral contract and [`tickets.md`](tickets.md)
for the implementation ticket history.
