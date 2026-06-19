# Polymarket CLOB: how BUY/SELL maps to outcomes

Each market outcome (YES and NO) is a **separate conditional token with its own
`token_id`**. In `py-clob-client`, `OrderArgs.token_id` is documented as "TokenID
of the Conditional token asset being traded", and the order builder always uses
that one fixed `token_id`; `side` only flips which leg is maker vs taker:

- **BUY**  → pay USDC collateral to *acquire* that token (open the position).
- **SELL** → give up that token for USDC collateral (close/exit the position).

`side` does **not** switch outcomes. Entering NO = **BUY on the NO `token_id`**,
NOT SELL on the YES `token_id`. Selling YES just closes a YES position; it does
not open NO. Our `scheduler/jobs.py` already picks the correct per-outcome
`token_id`, so every *entry* (YES or NO) is a BUY; only real exits are SELL.
Constants: `BUY = "BUY"`, `SELL = "SELL"`.
