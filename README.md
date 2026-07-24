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

The CLI is backed by the supplied HTTP API. It calls `/api/lookup-account` only
after a valid account ID and calls `/api/process-payment` only after strict
verification, amount validation, and card validation succeed:

```bash
python main.py
# or, after installing the project:
payment-collection-agent
```

Try this sample conversation (the expiry year can be any future year):

```text
You: account id ACC1002
You: Rajarajeswari Balasubramaniam
You: DOB 1985-11-23
You: 100
You: cardholder name: Rajarajeswari Balasubramaniam, card number: 4532 0151 1283 0366, CVV: 123, expiry: 12/2027
```

Another sample conversation is:

```text
You: account id ACC1001
You: Nithin Jain
You: DOB 1990-05-14
You: pay the outstanding balance
You: cardholder name: Demo Cardholder, card number: 4532 0151 1283 0366, CVV: 123, expiry: 12/2027
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
# or
python main.py --evaluate
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
