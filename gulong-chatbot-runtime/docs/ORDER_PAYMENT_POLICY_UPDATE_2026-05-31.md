# Runtime V7 Order Payment Policy Update - 2026-05-31

## Scope

Runtime V7 now owns a shared delivery, payment, and installment policy source in
`runtime_v7.delivery_payment_policy`.

Runtime V7 also owns assigned-agent contact routing in
`runtime_v7.contact_policy`.

## Behavior

- Order FAQ answers for payment, delivery fee, delivery process, and installment
  policy use the V7 policy source before falling back to FAQ/RAG chunks.
- Delivery quote/order math uses the same source for shipping fee rules:
  Premium products have free delivery; Budget, Economy, and Mid-Range products
  use the standard PHP 500 delivery fee. Apollo is no longer a free-delivery
  brand override unless the trusted product category itself is Premium.
- Payment request routing uses the same source for delivery payment behavior:
  delivery credit card/debit card/installment requests use full-payment 2C2P.
  Metro Manila delivery with GCash/online payment uses full payment. Outside
  Metro Manila COD stays on reservation-fee collection.
- The payment renderer keeps exact runtime-owned links, QR URLs, account
  numbers, and amounts, with light customer-facing formatting/icons.
- Order/contact FAQ responses resolve runtime-known profile assignment before
  returning contact numbers. Jeanel Co-assigned users receive the Call/Text and
  Viber numbers; everyone else receives the default Gulong contact number.
- `get_business_contact` is a general read-only tool exposed independently of
  order-domain tooling. The model decides whether to use it from the tool schema
  and prompt contract, so early contact questions are not blocked by order
  capability selection.

## Tests

Covered by Runtime V7 tests for:

- V7-owned order FAQ spiels
- Premium-only free delivery policy
- Metro Manila delivery payment policy
- outside Metro Manila COD reservation fee
- delivery card/installment full-payment 2C2P
- assigned-agent contact number routing
- general contact tool exposure without order-domain selection
